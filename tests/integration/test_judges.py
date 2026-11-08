"""Offline tests for judges: visibility, parsing, the judge step and judge-vs-state analysis."""

from __future__ import annotations

import asyncio
import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from safeagenteval.agents.chat import ChatEntry, ChatResponse
from safeagenteval.agents.providers import ModelSpec
from safeagenteval.backends.banking.backend import BankingBackend
from safeagenteval.core.models import (
    AgentTurn,
    Configuration,
    Domain,
    JsonObject,
    Message,
    Role,
    ToolCall,
    ToolSpec,
)
from safeagenteval.harness.runner import run_scenario
from safeagenteval.judges import JudgeVerdict, JudgeVisibility, parse_judgement, render_transcript
from safeagenteval.pilot.__main__ import main
from safeagenteval.pilot.analysis import analyze, state_passed
from safeagenteval.pilot.config import PilotConfig, RunPaths, load_config
from safeagenteval.pilot.extraction import extract_pilot
from safeagenteval.pilot.judging import judge_pilot, load_judgement
from safeagenteval.pilot.labels import export_run_labels, read_rows
from safeagenteval.pilot.runner import load_run, run_pilot
from safeagenteval.scenarios.loader import discover_scenarios

ROOT = Path(__file__).parents[2]
TRANSFER_ARGS: JsonObject = {
    "source_account_id": "account-checking",
    "payee_id": "payee-alice",
    "amount": "100.00",
    "currency": "USD",
}
PASS = json.dumps({"safe": True, "helpful": True, "honest": True, "verdict": "pass", "issues": []})


def _scenario(scenario_id: str) -> Any:
    found = {
        s.scenario_id: s for s in discover_scenarios(ROOT / "safeorderbench", domain=Domain.BANKING)
    }
    return found[scenario_id]


class TransferThenReply:
    """Scripted agent: transfer on each customer message, then say it is pending."""

    async def respond(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> AgentTurn:
        if messages[-1].role is Role.CUSTOMER:
            return AgentTurn(
                tool_calls=(
                    ToolCall(call_id="t1", name="initiate_transfer", arguments=TRANSFER_ARGS),
                )
            )
        return AgentTurn(reply="The transfer is pending.")


class EagerLiar:
    """Fake model: transfers immediately, then always claims success."""

    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        if history[-1].role == "user":
            call = ToolCall(call_id="toolu_1", name="initiate_transfer", arguments=TRANSFER_ARGS)
            return ChatResponse(tool_calls=(call,), model="fake", latency_seconds=0.01)
        return ChatResponse(
            text="Done: I sent $100.00 to Alice.", model="fake", latency_seconds=0.0
        )


class NoClaims:
    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        return ChatResponse(text='{"claims": []}', model="fake-extractor", latency_seconds=0.0)


class Judge:
    """Fake judge: passes everything, except that it returns garbage when told to."""

    def __init__(self, garble: bool = False) -> None:
        self.garble = garble
        self.prompts: list[str] = []

    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        self.prompts.append(history[-1].content)
        text = "I think it was fine." if self.garble else f"```json\n{PASS}\n```"
        return ChatResponse(text=text, model="fake-judge", latency_seconds=0.0)


class Failing:
    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        raise ConnectionError("network down")


def _spec(name: str) -> ModelSpec:
    return ModelSpec(name=name, provider="openai", model="fake", api_key_env="UNUSED")


def _config(tmp_path: Path) -> PilotConfig:
    return PilotConfig(
        experiment_id="test",
        output_dir=tmp_path / "out",
        benchmark_root=ROOT / "safeorderbench",
        session_customer_id="customer-001",
        agent_prompt=ROOT / "experiments" / "prompts" / "banking_agent_v1.md",
        extractor_prompt=ROOT / "experiments" / "prompts" / "claim_extractor_v1.md",
        judge_prompt=ROOT / "experiments" / "prompts" / "judge_v1.md",
        models=(_spec("liar"),),
        extractor=_spec("extractor"),
        judges=(_spec("j-pass"), _spec("j-garbled")),
    )


def _quiet(_: str) -> None:
    pass


# --- visibility --------------------------------------------------------------


def test_each_visibility_level_shows_only_its_evidence() -> None:
    scenario = _scenario("banking.partial_failure.timeout_after_commit_001")
    result = asyncio.run(
        run_scenario(
            scenario, TransferThenReply(), BankingBackend(scenario.initial_state), Configuration.C0
        )
    )
    replies = render_transcript(result.events, JudgeVisibility.REPLIES)
    tools = render_transcript(result.events, JudgeVisibility.TOOL_CALLS)
    full = render_transcript(result.events, JudgeVisibility.FULL_TRACE)

    assert "CUSTOMER:" in replies and "ASSISTANT: The transfer is pending." in replies
    assert "initiate_transfer" not in replies

    assert "ASSISTANT TOOL CALL: initiate_transfer" in tools
    assert "status=timeout" in tools
    # The commit hidden by the fault is ground truth: only the full trace reveals it.
    assert "committed=true" not in tools and "BACKEND RECORD CHANGED" not in tools

    assert "committed=true" in full and "the assistant was shown instead" in full
    assert "BACKEND RECORD CHANGED" in full and "FINAL BACKEND STATE" in full
    assert "ACCESS CONTROL: admitted initiate_transfer" in full

    for text in (replies, tools, full):
        assert "resolved_intent_id" not in text and "authorized_final_states" not in text


# --- parsing ---------------------------------------------------------------------


def test_parse_judgement_accepts_fenced_json() -> None:
    assessment, error = parse_judgement(f"```json\n{PASS}\n```")
    assert error is None and assessment is not None
    assert assessment.verdict is JudgeVerdict.PASS and assessment.safe


@pytest.mark.parametrize(
    "raw",
    [
        "no json",
        "{bad json}",
        json.dumps({"safe": True, "helpful": True, "honest": True, "verdict": "maybe"}),
        json.dumps({"safe": "yes", "helpful": True, "honest": True, "verdict": "pass"}),
    ],
)
def test_parse_judgement_rejects_malformed_output(raw: str) -> None:
    assessment, error = parse_judgement(raw)
    assert assessment is None and error is not None


# --- judge step and analysis ---------------------------------------------------------


def test_judge_step_and_judge_versus_state_analysis(tmp_path: Path) -> None:
    config = _config(tmp_path)
    asyncio.run(run_pilot(config, client_factory=lambda _: EagerLiar(), progress=_quiet))
    asyncio.run(extract_pilot(config, client_factory=lambda _: NoClaims(), progress=_quiet))

    clients = {"j-pass": Judge(), "j-garbled": Judge(garble=True)}
    summary = asyncio.run(
        judge_pilot(config, client_factory=lambda spec: clients[spec.name], progress=_quiet)
    )
    assert summary.completed == 28 * 2 * 3 and not summary.api_failures
    again = asyncio.run(
        judge_pilot(config, client_factory=lambda spec: clients[spec.name], progress=_quiet)
    )
    assert again.completed == 0 and again.skipped == 28 * 2 * 3

    paths = RunPaths(config)
    record = load_judgement(
        paths.judgement(
            "j-pass",
            JudgeVisibility.REPLIES,
            "liar",
            Configuration.C0,
            "banking.confirmation_gate.transfer_confirmation_001",
        )
    )
    assert record.judgement.passed is True and len(record.judge_prompt_sha256) == 64
    assert "initiate_transfer" not in record.judgement.transcript

    runs = [load_run(path) for path in sorted((paths.root / "runs").glob("*/*/*.json"))]
    state_failures = sum(not state_passed(saved) for saved in runs)
    unauthorized = sum(saved.result.state_score.unauthorized_action for saved in runs)
    assert state_failures > 0 and unauthorized > 0

    analysis: dict[str, Any] = json.loads(json.dumps(analyze(config)))
    entries = {(e["judge"], e["visibility"]): e for e in analysis["judges"]}
    assert len(entries) == 6

    always_pass = entries[("j-pass", "replies")]["overall"]
    assert always_pass["unparsed"] == 0
    assert always_pass["judge_miss_rate"]["count"] == state_failures
    assert always_pass["judge_miss_rate"]["n"] == 28
    assert always_pass["judge_miss_rate_unauthorized"]["count"] == unauthorized
    assert always_pass["misses"]["with_unauthorized_action"] == unauthorized
    assert len(always_pass["misses"]["runs"]) == state_failures
    assert always_pass["detection_rate"] == {
        "count": 0,
        "n": state_failures,
        "rate": 0.0,
        "ci95": always_pass["detection_rate"]["ci95"],
    }
    assert always_pass["unauthorized_detection_rate"]["n"] == unauthorized
    other = entries[("j-pass", "replies")]["agreement_with_other_judges"]["j-garbled"]
    assert other["n"] == 0

    garbled = entries[("j-garbled", "full_trace")]["overall"]
    assert garbled["unparsed"] == 28 and garbled["judge_miss_rate"]["n"] == 0

    claims = analysis["cells"][0]["claims"]
    assert claims["runs_with_contradiction_automatic"]["n"] == 14

    # Humans label every run the way the state verdict does, so agreement is perfect.
    runs_csv = export_run_labels(config)
    rows = read_rows(runs_csv)
    assert len(rows) == 28 and "BLOCKED" not in rows[0]["scenario_description"]
    verdicts = {
        f"liar|{s.configuration.value}|{s.result.scenario_id}": state_passed(s) for s in runs
    }
    for row in rows:
        row["label_pass"] = "y" if verdicts[row["run_key"]] else "n"
    with runs_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    assert all(row["label_pass"] for row in read_rows(export_run_labels(config)))

    relabeled: dict[str, Any] = json.loads(json.dumps(analyze(config)))
    assert relabeled["human_run_labels"]["labeled_runs"] == 28
    assert relabeled["human_run_labels"]["state_vs_human_kappa"] == 1.0
    agreement = {(e["judge"], e["visibility"]): e for e in relabeled["judges"]}
    assert agreement[("j-pass", "replies")]["overall"]["human_agreement"]["n"] == 28
    assert "## Judges versus state" in (config.output_dir / "analysis.md").read_text(
        encoding="utf-8"
    )


def test_judge_sees_the_visibility_description(tmp_path: Path) -> None:
    config = _config(tmp_path)
    asyncio.run(run_pilot(config, limit=1, client_factory=lambda _: EagerLiar(), progress=_quiet))
    judge = Judge()
    asyncio.run(
        judge_pilot(
            config,
            judges=("j-pass",),
            visibilities=(JudgeVisibility.REPLIES,),
            client_factory=lambda _: judge,
            progress=_quiet,
        )
    )
    assert len(judge.prompts) == 1
    assert judge.prompts[0].startswith("You are shown the conversation only")


def test_judge_api_failures_are_not_saved(tmp_path: Path) -> None:
    config = _config(tmp_path)
    asyncio.run(run_pilot(config, limit=2, client_factory=lambda _: EagerLiar(), progress=_quiet))
    summary = asyncio.run(judge_pilot(config, client_factory=lambda _: Failing(), progress=_quiet))
    assert summary.completed == 0 and len(summary.api_failures) == 2 * 2 * 3
    assert not list((config.output_dir / "judgements").glob("**/*.json"))


# --- configuration and command line ----------------------------------------------------


def test_shipped_config_has_two_judge_families_none_of_them_agents() -> None:
    config = load_config(ROOT / "experiments" / "configs" / "pilot_v1.yaml", root=ROOT)
    agent_models = {model.model for model in config.models}
    assert len(config.judges) == 2
    assert {judge.provider for judge in config.judges} == {"openai", "anthropic"}
    assert not agent_models & {judge.model for judge in config.judges}
    assert config.judge_visibilities == tuple(JudgeVisibility)


def test_judges_require_a_prompt(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="judge_prompt"):
        PilotConfig.model_validate({**_config(tmp_path).model_dump(), "judge_prompt": None})


def test_cli_judge_refuses_missing_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    shipped = (ROOT / "experiments" / "configs" / "pilot_v1.yaml").read_text(encoding="utf-8")
    judge_key = "model: gpt-5.5\n    api_key_env: OPENAI_API_KEY"
    shipped = shipped.replace("\r\n", "\n")
    assert judge_key in shipped
    config_path = tmp_path / "pilot.yaml"
    config_path.write_text(
        shipped.replace(judge_key, "model: gpt-5.5\n    api_key_env: SAFEAGENTEVAL_TEST_UNSET"),
        encoding="utf-8",
    )
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("SAFEAGENTEVAL_TEST_UNSET", raising=False)
    assert main(["judge", str(config_path)]) == 2
    assert "SAFEAGENTEVAL_TEST_UNSET" in capsys.readouterr().err
