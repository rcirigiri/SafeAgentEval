"""LLMJudge and claim verification over black-box runs.

The judge is an evaluation-side model: it grades a recorded run without
the answer key, and its verdict is compared with the deterministic
final-state verdict afterwards. It never decides the agent's score.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from typer.testing import CliRunner

import safeagenteval.cli.judge_cmd as judge_cmd
import safeagenteval.cli.run_cmd as run_cmd
from safeagenteval.backends.state_provider import InMemoryStateProvider
from safeagenteval.claims.llm_extractor import LLMClaimExtractor, parse_claims
from safeagenteval.claims.verifier import (
    ActionClaim,
    ClaimStatus,
    ClaimVerdictValue,
    verify_claims,
)
from safeagenteval.cli import app
from safeagenteval.cli.common import parse_model_spec
from safeagenteval.core.models import Domain
from safeagenteval.harness.session_runner import run_session_scenario
from safeagenteval.judges.llm_judge import LLMJudge, parse_judgement
from safeagenteval.judges.transcript import JudgeVisibility, render_transcript
from safeagenteval.llm.client import (
    GEMINI_OPENAI_BASE_URL,
    OpenAITextClient,
    TextResponse,
    build_client,
)
from safeagenteval.mocks.banking_session import reference_session_pair, unsafe_session_pair
from safeagenteval.reporting import SavedRunRecord
from safeagenteval.scenarios.loader import discover_scenarios

ROOT = Path(__file__).parents[2]
BENCHMARK = ROOT / "safeorderbench"
BANKING = {s.scenario_id: s for s in discover_scenarios(BENCHMARK, domain=Domain.BANKING)}


class FixedText:
    """TextClient stub returning a fixed reply."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def complete(self, system: str, user: str) -> TextResponse:
        del system, user
        return TextResponse(text=self._text, model="stub", latency_seconds=0.0)


def _run(scenario_id: str, *, safe: bool):  # type: ignore[no-untyped-def]
    scenario = BANKING[scenario_id]
    pair = reference_session_pair if safe else unsafe_session_pair
    agent, provider = pair(scenario)
    return asyncio.run(run_session_scenario(scenario, agent, provider))


def test_gemini_extractor_spec_routes_to_openai_compatible_endpoint(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    spec = parse_model_spec("gemini:gemini-2.5-flash")
    assert spec.provider == "gemini"
    assert spec.api_key_env == "GEMINI_API_KEY"
    client = build_client(spec)
    assert isinstance(client, OpenAITextClient)
    assert client._spec.base_url == GEMINI_OPENAI_BASE_URL


def test_judge_agrees_with_state_verdict_on_safe_run() -> None:
    result = _run("banking.confirmation_gate.benign_transfer_001", safe=True)
    judge = LLMJudge(
        FixedText('{"verdict": "pass", "safe": true, "helpful": true, "honest": true}'),
        "rubric",
        JudgeVisibility.REPLIES,
    )
    judgement = asyncio.run(judge.judge(result.events))
    assert judgement.passed is True
    assert result.state_score.final_state_correct  # ground truth the judge is compared to


def test_judge_miss_is_visible_against_state_verdict() -> None:
    # Unsafe agent transfers without confirmation; a lenient judge
    # passes it. The deterministic verdict is the reference: this is a miss.
    result = _run("banking.confirmation_gate.transfer_without_confirmation_001", safe=False)
    assert not result.state_score.final_state_correct
    judge = LLMJudge(
        FixedText('{"verdict": "pass", "safe": true, "helpful": true, "honest": true}'),
        "rubric",
        JudgeVisibility.REPLIES,
    )
    judgement = asyncio.run(judge.judge(result.events))
    assert judgement.passed is True  # judge passed a truly failed run == miss


def test_transcript_never_shows_answer_key() -> None:
    result = _run("banking.confirmation_gate.benign_transfer_001", safe=True)
    for visibility in JudgeVisibility:
        text = render_transcript(result.events, visibility)
        assert "authorized_final_states" not in text
        assert "CUSTOMER:" in text and "ASSISTANT:" in text
    with_state = render_transcript(result.events, JudgeVisibility.WITH_STATE)
    assert "FINAL STATE:" in with_state


def test_parse_judgement_rejects_malformed_output() -> None:
    assessment, error = parse_judgement("not json")
    assert assessment is None and error
    assessment, error = parse_judgement('{"verdict": "maybe"}')
    assert assessment is None and error


def test_claims_verified_against_final_state() -> None:
    result = _run("banking.confirmation_gate.benign_transfer_001", safe=True)
    claim = ActionClaim(
        claim_id="c1",
        reply_sequence=1,
        turn_id="confirm",
        action="initiate_transfer",
        status=ClaimStatus.DONE,
        source_text="Transfer completed: $100.00 sent.",
        attributes={"amount": "100.00"},
        path="transfers",
    )
    verdicts = verify_claims((claim,), result.events)
    assert verdicts[0].verdict is ClaimVerdictValue.VERIFIED

    false_claim = claim.model_copy(update={"attributes": {"amount": "99.00"}})
    verdicts = verify_claims((false_claim,), result.events)
    assert verdicts[0].verdict is ClaimVerdictValue.CONTRADICTED


def test_attributes_scattered_across_objects_do_not_verify() -> None:
    # amount from the transfer, balance from the account: no single
    # subtree under transfers holds both, so it must not verify.
    result = _run("banking.confirmation_gate.benign_transfer_001", safe=True)
    claim = ActionClaim(
        claim_id="c9",
        reply_sequence=1,
        turn_id="confirm",
        action="initiate_transfer",
        status=ClaimStatus.DONE,
        source_text="Transfer completed.",
        attributes={"amount": "100.00", "balance": "1900.00"},
        path="transfers",
    )
    verdicts = verify_claims((claim,), result.events)
    assert verdicts[0].verdict is ClaimVerdictValue.CONTRADICTED

    scoped = claim.model_copy(update={"attributes": {"amount": "100.00"}})
    verdicts = verify_claims((scoped,), result.events)
    assert verdicts[0].verdict is ClaimVerdictValue.VERIFIED

    missing_path = claim.model_copy(update={"path": "refunds"})
    verdicts = verify_claims((missing_path,), result.events)
    assert verdicts[0].verdict is ClaimVerdictValue.CONTRADICTED


def test_extractor_parses_typed_claims_without_seeing_outcome() -> None:
    claims, error, dropped = parse_claims(
        '{"claims": [{"action": "initiate_transfer", "status": "done",'
        ' "attributes": {"amount": "100.00"}, "source_text": "Transfer completed"}]}',
        reply="Transfer completed: $100.00 sent.",
        reply_sequence=3,
        turn_id="confirm",
        claim_prefix="claim-3",
    )
    assert error is None and dropped == 0
    assert len(claims) == 1 and claims[0].status is ClaimStatus.DONE

    extractor = LLMClaimExtractor(FixedText('{"claims": []}'), "prompt", "reference")
    extracted = asyncio.run(extractor.extract("Okay.", 1, "request"))
    assert extracted == ()
    assert len(extractor.records) == 1


def test_judge_command_reports_agreement(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    result = _run("banking.confirmation_gate.benign_transfer_001", safe=True)
    record = SavedRunRecord(
        scenario_id=result.scenario_id,
        agent="stub",
        passed=result.passed,
        completed=result.completed,
        final_state=result.final_state,
        state_score=result.state_score,
        events=result.events,
        claims=result.claims,
        claim_verdicts=result.claim_verdicts,
        reply_violations=result.reply_violations,
    )
    (tmp_path / "run.json").write_text(record.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        judge_cmd,
        "build_client",
        lambda spec: FixedText(
            '{"verdict": "pass", "safe": true, "helpful": true, "honest": true}'
        ),
    )
    ran = CliRunner().invoke(app, ["judge", str(tmp_path), "--model", "openai:stub"])
    assert ran.exit_code == 0, ran.output
    import json

    payload = json.loads(ran.output)
    assert payload["agreement_rate"] == 1.0
    assert payload["judgements"][0]["judge_verdict"] == "pass"


def test_run_command_wires_claim_extractor(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(run_cmd, "build_client", lambda spec: FixedText('{"claims": []}'))
    out = tmp_path / "runs"
    ran = CliRunner().invoke(
        app,
        [
            "run",
            "--agent",
            "session-reference",
            "--scenario",
            "banking.confirmation_gate.benign_transfer_001",
            "--extractor-model",
            "openai:stub",
            "--out",
            str(out),
        ],
    )
    assert ran.exit_code == 0, ran.output
    import json

    records = [json.loads(p.read_text()) for p in out.glob("*.json")]
    assert len(records) == 1
    assert records[0]["claims"] == [] and records[0]["claim_verdicts"] == []


def test_state_provider_is_the_judges_only_state_source() -> None:
    # A run graded from an untouched provider cannot be correct for the
    # benign scenario: the snapshot, not the reply, is ground truth.
    scenario = BANKING["banking.confirmation_gate.benign_transfer_001"]
    agent, _provider = reference_session_pair(scenario)
    result = asyncio.run(run_session_scenario(scenario, agent, InMemoryStateProvider()))
    assert not result.state_score.final_state_correct
