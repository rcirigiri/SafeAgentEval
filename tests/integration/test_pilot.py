"""Offline tests for the real-model pilot, using scripted fake chat clients."""

from __future__ import annotations

import asyncio
import csv
import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from safeagenteval.agents.chat import ChatAgent, ChatEntry, ChatResponse, parse_tool_arguments
from safeagenteval.agents.providers import (
    ModelSpec,
    parse_anthropic_response,
    parse_openai_response,
    parse_responses_response,
    to_anthropic_messages,
    to_openai_messages,
    to_openai_tools,
    to_responses_input,
    to_responses_tools,
)
from safeagenteval.claims.llm_extractor import parse_claims
from safeagenteval.claims.verifier import ClaimStatus
from safeagenteval.core.models import JsonObject, Message, Role, ToolCall, ToolEffect, ToolSpec
from safeagenteval.pilot.__main__ import main
from safeagenteval.pilot.analysis import analyze, cohen_kappa, wilson_interval
from safeagenteval.pilot.config import PilotConfig, RunPaths, load_config
from safeagenteval.pilot.extraction import extract_pilot
from safeagenteval.pilot.labels import export_labels, read_rows
from safeagenteval.pilot.runner import load_run, plan_runs, run_pilot

ROOT = Path(__file__).parents[2]
GATE_SCENARIO = "banking.confirmation_gate.transfer_confirmation_001"
TRANSFER_ARGS: JsonObject = {
    "source_account_id": "account-checking",
    "payee_id": "payee-alice",
    "amount": "100.00",
    "currency": "USD",
}


class EagerLiar:
    """Fake model: transfers immediately, then always claims success."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        self.calls += 1
        if history[-1].role == "user":
            call = ToolCall(call_id="toolu_1", name="initiate_transfer", arguments=TRANSFER_ARGS)
            return ChatResponse(tool_calls=(call,), model="fake", latency_seconds=0.01)
        return ChatResponse(
            text="Done: I sent $100.00 to Alice.",
            model="fake",
            latency_seconds=0.02,
            input_tokens=10,
            output_tokens=5,
        )


class FakeExtractor:
    """Fake extractor: a 'sent' reply is a done claim for Alice."""

    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        text = history[-1].content
        claims = (
            [
                {
                    "action": "initiate_transfer",
                    "status": "done",
                    "attributes": {"payee_id": "payee-alice", "amount": "100.00"},
                    "source_text": "I sent $100.00 to Alice.",
                }
            ]
            if "sent" in text
            else []
        )
        return ChatResponse(
            text="```json\n" + json.dumps({"claims": claims}) + "\n```",
            model="fake-extractor",
            latency_seconds=0.0,
        )


class Failing:
    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        raise ConnectionError("network down")


def _config(tmp_path: Path, models: Sequence[str] = ("liar",)) -> PilotConfig:
    def spec(name: str) -> ModelSpec:
        return ModelSpec(name=name, provider="openai", model="fake", api_key_env="UNUSED")

    return PilotConfig(
        experiment_id="test",
        output_dir=tmp_path / "out",
        benchmark_root=ROOT / "safeorderbench",
        session_customer_id="customer-001",
        agent_prompt=ROOT / "experiments" / "prompts" / "banking_agent_v1.md",
        extractor_prompt=ROOT / "experiments" / "prompts" / "claim_extractor_v1.md",
        models=tuple(spec(name) for name in models),
        extractor=spec("extractor"),
    )


def _quiet(_: str) -> None:
    pass


# --- adapter and conversions -------------------------------------------------


def test_chat_agent_maps_tool_results_to_provider_ids_and_dedupes_call_ids() -> None:
    class TwoCalls:
        def __init__(self) -> None:
            self.histories: list[list[ChatEntry]] = []

        async def complete(
            self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
        ) -> ChatResponse:
            self.histories.append(list(history))
            call = ToolCall(call_id="dup", name="lookup_account", arguments={"account_id": "a"})
            return ChatResponse(tool_calls=(call, call), model="m", latency_seconds=0)

    client = TwoCalls()
    agent = ChatAgent(client, "system")
    turn = asyncio.run(
        agent.respond((Message(role=Role.CUSTOMER, content="hi", turn_id="t1"),), ())
    )
    assert [call.call_id for call in turn.tool_calls] == ["dup", "dup#2"]

    tool_messages = tuple(
        Message(
            role=Role.TOOL,
            content=json.dumps({"call_id": cid, "name": "lookup_account"}),
            turn_id="t1",
        )
        for cid in ("dup", "dup#2")
    )
    history = (Message(role=Role.CUSTOMER, content="hi", turn_id="t1"), *tool_messages)
    asyncio.run(agent.respond(history, ()))
    last = client.histories[-1]
    assert [entry.role for entry in last] == ["user", "assistant", "tool", "tool"]
    assert [entry.tool_call_id for entry in last[2:]] == ["dup", "dup"]


def test_chat_agent_records_api_errors() -> None:
    agent = ChatAgent(Failing(), "system")
    with pytest.raises(ConnectionError):
        asyncio.run(agent.respond((Message(role=Role.CUSTOMER, content="x", turn_id="t"),), ()))
    assert agent.api_error is not None and "network down" in agent.api_error


def test_parse_tool_arguments_keeps_malformed_input() -> None:
    assert parse_tool_arguments('{"a": 1}') == {"a": 1}
    assert parse_tool_arguments("{oops") == {"_unparsed_arguments": "{oops"}
    assert parse_tool_arguments(None) == {}


def test_openai_conversion_round_trip() -> None:
    call = ToolCall(call_id="c1", name="initiate_transfer", arguments=TRANSFER_ARGS)
    history = (
        ChatEntry(role="user", content="send"),
        ChatEntry(role="assistant", tool_calls=(call,)),
        ChatEntry(role="tool", content="{}", tool_call_id="c1"),
    )
    messages = to_openai_messages("sys", history)
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[2]["content"] is None
    assert json.loads(messages[2]["tool_calls"][0]["function"]["arguments"]) == TRANSFER_ARGS
    assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": "{}"}
    tool = ToolSpec(
        name="t", description="d", input_schema={"type": "object"}, effect=ToolEffect.READ
    )
    assert to_openai_tools((tool,))[0]["function"]["parameters"] == {"type": "object"}

    function = SimpleNamespace(name="initiate_transfer", arguments=json.dumps(TRANSFER_ARGS))
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None, tool_calls=[SimpleNamespace(id="c9", function=function)]
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4),
        model="m",
    )
    parsed = parse_openai_response(response, 0.5)
    assert parsed.tool_calls[0].arguments == TRANSFER_ARGS
    assert (parsed.input_tokens, parsed.output_tokens) == (3, 4)


def test_anthropic_conversion_merges_tool_results_into_one_user_message() -> None:
    calls = (
        ToolCall(call_id="a", name="lookup_account", arguments={}),
        ToolCall(call_id="b", name="list_payees", arguments={}),
    )
    history = (
        ChatEntry(role="user", content="hi"),
        ChatEntry(role="assistant", content="Checking.", tool_calls=calls),
        ChatEntry(role="tool", content="r1", tool_call_id="a"),
        ChatEntry(role="tool", content="r2", tool_call_id="b"),
        ChatEntry(role="user", content="thanks"),
    )
    messages = to_anthropic_messages(history)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert [b["type"] for b in messages[1]["content"]] == ["text", "tool_use", "tool_use"]
    assert [b["type"] for b in messages[2]["content"]] == ["tool_result", "tool_result", "text"]

    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="ok"),
            SimpleNamespace(
                type="tool_use", id="t1", name="lookup_account", input={"account_id": "x"}
            ),
        ],
        usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        model="m",
        stop_reason="tool_use",
    )
    parsed = parse_anthropic_response(response, 0.1)
    assert parsed.text == "ok" and parsed.tool_calls[0].call_id == "t1"


def test_responses_conversion_and_parsing() -> None:
    call = ToolCall(call_id="call_1", name="initiate_transfer", arguments=TRANSFER_ARGS)
    history = (
        ChatEntry(role="user", content="send"),
        ChatEntry(role="assistant", content="On it.", tool_calls=(call,)),
        ChatEntry(role="tool", content='{"status": "success"}', tool_call_id="call_1"),
    )
    items = to_responses_input(history)
    assert items[0] == {"role": "user", "content": "send"}
    assert items[1] == {"role": "assistant", "content": "On it."}
    assert items[2]["type"] == "function_call" and items[2]["call_id"] == "call_1"
    assert json.loads(items[2]["arguments"]) == TRANSFER_ARGS
    assert items[3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"status": "success"}',
    }
    tool = ToolSpec(
        name="t", description="d", input_schema={"type": "object"}, effect=ToolEffect.READ
    )
    assert to_responses_tools((tool,))[0] == {
        "type": "function",
        "name": "t",
        "description": "d",
        "parameters": {"type": "object"},
        "strict": False,
    }

    response = SimpleNamespace(
        output=[
            SimpleNamespace(type="reasoning"),
            SimpleNamespace(
                type="message", content=[SimpleNamespace(type="output_text", text="Sent.")]
            ),
            SimpleNamespace(
                type="function_call",
                call_id="call_2",
                name="lookup_account",
                arguments='{"account_id": "a"}',
            ),
        ],
        usage=SimpleNamespace(input_tokens=5, output_tokens=6),
        model="m",
        status="completed",
        incomplete_details=None,
    )
    parsed = parse_responses_response(response, 0.2)
    assert parsed.text == "Sent." and parsed.stop_reason == "completed"
    assert parsed.tool_calls[0].arguments == {"account_id": "a"}


# --- extractor parsing ---------------------------------------------------------


def test_parse_claims_accepts_fenced_json_and_drops_invalid_items() -> None:
    items = [
        {
            "action": "initiate_transfer",
            "status": "done",
            "attributes": {"payee_id": "payee-alice", "amount": 100, "bogus": "x"},
        },
        {"action": "wire", "status": "done"},
        {"action": "initiate_transfer", "status": "maybe"},
    ]
    raw = "```json\n" + json.dumps({"claims": items}) + "\n```"
    claims, error, dropped = parse_claims(
        raw, reply="r", reply_sequence=3, turn_id="t", claim_prefix="c"
    )
    assert error is None and dropped == 2
    assert claims[0].status is ClaimStatus.DONE
    assert claims[0].attributes == {"payee_id": "payee-alice", "amount": "100"}
    assert claims[0].source_text == "r"


@pytest.mark.parametrize("raw", ["no json here", "{not json}", '{"other": []}'])
def test_parse_claims_reports_errors(raw: str) -> None:
    claims, error, _ = parse_claims(raw, reply="r", reply_sequence=1, turn_id="t", claim_prefix="c")
    assert claims == () and error is not None


# --- statistics ------------------------------------------------------------------


def test_wilson_and_kappa() -> None:
    low, high = wilson_interval(7, 7)
    assert 0.6 < low < 0.7 and high == 1.0
    assert wilson_interval(0, 0) == (0.0, 0.0)
    assert cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert cohen_kappa([True, True], [True, True]) is None


# --- end-to-end pipeline -----------------------------------------------------------


def test_pilot_pipeline_end_to_end(tmp_path: Path) -> None:
    config = _config(tmp_path)
    summary = asyncio.run(run_pilot(config, client_factory=lambda _: EagerLiar(), progress=_quiet))
    assert summary.completed == 28 and not summary.api_failures
    assert all(plan.done for plan in plan_runs(config))

    again = asyncio.run(run_pilot(config, client_factory=lambda _: EagerLiar(), progress=_quiet))
    assert again.completed == 0 and again.skipped == 28

    paths = RunPaths(config)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert len(manifest["agent_prompt_sha256"]) == 64
    c2_run = load_run(paths.run("liar", config.configurations[1], GATE_SCENARIO))
    assert c2_run.result.state_score.blocked_action_attempts == 1
    assert "customer-001" in c2_run.system_prompt and "{{" not in c2_run.system_prompt

    extracted = asyncio.run(
        extract_pilot(config, client_factory=lambda _: FakeExtractor(), progress=_quiet)
    )
    assert extracted.completed == 28

    claims_csv, replies_csv = export_labels(config)
    rows = read_rows(claims_csv)
    assert len(rows) == len(read_rows(replies_csv)) >= 28
    blocked = [r for r in rows if r["configuration"] == "C2" and r["scenario_id"] == GATE_SCENARIO]
    assert blocked[0]["verdict"] == "contradicted"
    assert "BLOCKED initiate_transfer" in blocked[0]["trace_summary"]

    # Annotate every contradiction as genuine and check labels survive re-export.
    for row in rows:
        if row["verdict"] == "contradicted":
            row["label_extraction_correct"] = "y"
            row["label_verdict_correct"] = "yes"
    with claims_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    export_labels(config)
    relabeled = read_rows(claims_csv)
    assert sum(r["label_verdict_correct"] == "yes" for r in relabeled) == sum(
        r["verdict"] == "contradicted" for r in rows
    )

    analyze(config)
    analysis: dict[str, Any] = json.loads(
        (config.output_dir / "analysis.json").read_text(encoding="utf-8")
    )
    cells = {cell["model"] + cell["configuration"]: cell for cell in analysis["cells"]}
    c0, c2 = cells["liarC0"], cells["liarC2"]
    assert c0["adversarial"]["unauthorized_action"]["count"] > 0
    assert c2["adversarial"]["unauthorized_action"]["count"] == 0
    assert c2["claims"]["contradicted_confirmed"] > 0
    assert c2["claims"]["contradicted_unlabeled"] == 0
    assert c2["claims"]["runs_authorized_state_with_contradiction_confirmed"] > 0
    assert (config.output_dir / "analysis.md").read_text(encoding="utf-8").startswith("# Pilot")


def test_api_failures_are_not_saved_and_are_retried(tmp_path: Path) -> None:
    config = _config(tmp_path)
    summary = asyncio.run(
        run_pilot(config, limit=None, client_factory=lambda _: Failing(), progress=_quiet)
    )
    assert summary.completed == 0 and len(summary.api_failures) == 28
    assert not list((config.output_dir / "runs").glob("**/*.json"))


def test_limit_and_model_selection(tmp_path: Path) -> None:
    config = _config(tmp_path, models=("a", "b"))
    summary = asyncio.run(
        run_pilot(
            config, models=("b",), limit=3, client_factory=lambda _: EagerLiar(), progress=_quiet
        )
    )
    assert summary.completed == 3
    assert {p.parent.parent.name for p in (config.output_dir / "runs").glob("*/*/*.json")} == {"b"}


def test_shipped_config_loads() -> None:
    config = load_config(ROOT / "experiments" / "configs" / "pilot_v1.yaml", root=ROOT)
    assert len(config.models) == 5
    assert config.extractor.name not in {model.name for model in config.models}
    assert config.extractor.model not in {model.model for model in config.models}


def test_cli_refuses_placeholders_and_missing_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    shipped = (ROOT / "experiments" / "configs" / "pilot_v1.yaml").read_text(encoding="utf-8")
    config_path = tmp_path / "pilot.yaml"
    config_path.write_text(
        shipped.replace("model: gpt-4.1-mini-2025-04-14", "model: REPLACE_ME").replace(
            "api_key_env: HF_TOKEN", "api_key_env: SAFEAGENTEVAL_TEST_UNSET"
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("SAFEAGENTEVAL_TEST_UNSET", raising=False)
    assert main(["run", str(config_path)]) == 2
    err = capsys.readouterr().err
    assert "REPLACE_ME" in err and "SAFEAGENTEVAL_TEST_UNSET" in err
