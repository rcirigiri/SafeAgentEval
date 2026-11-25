"""Run the black-box pilot: real LLM session agents on the released pack.

Two models act as agents under test through the black-box interface only
(one utterance in, one reply out; their tool use is internal), on the 16
released banking scenarios: ``claude-opus-5-5`` and ``gpt-6-luna``.
A third model extracts claims from replies for deterministic
verification; two further models (neither under test) judge every run at
both visibilities. Runs use the latest grading design: per-turn state
snapshots (claims graded against the state in force when spoken), the
harness provider-trust tier, and a randomized provider probe before
each run. All artifacts land in ``artifacts/pilot/blackbox_v3``:

    runs/<model>/*.json          SavedRunRecords (deterministic verdicts)
    judgements/<judge>/<visibility>/<model>/*.json
    labels/{claims,replies,runs}.csv   blank human-labeling sheets
    manifest.json

Phases are resumable: ``--phase runs|judges|labels|all``. Keys come from
the environment / local ``.env`` (OPENAI_API_KEY, ANTHROPIC_API_KEY).

    python scripts/run_blackbox_pilot.py --phase all --repeats 2
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from agentsafetyrecord.agents.llm_session import llm_session_pair
from agentsafetyrecord.cli.run_cmd import _run_all
from agentsafetyrecord.core.models import Domain
from agentsafetyrecord.judges.llm_judge import LLMJudge
from agentsafetyrecord.judges.transcript import JudgeVisibility, render_transcript
from agentsafetyrecord.llm.client import ModelSpec, build_client
from agentsafetyrecord.llm.prompts import JUDGE_PROMPT
from agentsafetyrecord.reporting import FileRecordSink, SavedRunRecord, load_records
from agentsafetyrecord.scenarios.loader import discover_scenarios

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "pilot" / "blackbox_v3"


def _spec(name: str, provider: str, model: str, key_env: str) -> ModelSpec:
    return ModelSpec(
        name=name,
        provider=provider,
        model=model,  # type: ignore[arg-type]
        api_key_env=key_env,
        temperature=None,
        max_tokens=1024,
    )


AGENTS: dict[str, ModelSpec] = {
    "claude-opus-5-5": _spec(
        "claude-opus-5-5", "anthropic", "claude-opus-5-5", "ANTHROPIC_API_KEY"
    ),
    "gpt-6-luna": _spec("gpt-6-luna", "openai", "gpt-6-luna", "OPENAI_API_KEY"),
}
EXTRACTOR = _spec("claude-sonnet-5-5", "anthropic", "claude-sonnet-5-5", "ANTHROPIC_API_KEY")
JUDGES: dict[str, ModelSpec] = {
    "claude-sonnet-5-5": EXTRACTOR,
    "gpt-6.2-sol": _spec("gpt-6.2-sol", "openai", "gpt-6.2-sol", "OPENAI_API_KEY"),
}


def phase_runs(repeats: int, concurrency: int) -> None:
    scenarios = discover_scenarios(ROOT / "safeorderbench", domain=Domain.BANKING)
    for label, spec in AGENTS.items():
        sink = FileRecordSink(OUT / "runs" / label)
        records = asyncio.run(
            _run_all(
                scenarios,
                repeats,
                llm_session_pair(spec),
                label,
                sink,
                EXTRACTOR,
                concurrency=concurrency,
                retries=1,
                retry_backoff=2.0,
                provider_trust="harness",
                provider_probe=True,
            )
        )
        passed = sum(1 for record in records if record.passed)
        print(f"{label}: {passed}/{len(records)} passed")
    manifest = {
        "pilot": "blackbox_v3",
        "date": date.today().isoformat(),
        "scenarios": [scenario.scenario_id for scenario in scenarios],
        "repeats": repeats,
        "agents": {label: spec.model_dump(mode="json") for label, spec in AGENTS.items()},
        "extractor": EXTRACTOR.model_dump(mode="json"),
        "judges": {label: spec.model_dump(mode="json") for label, spec in JUDGES.items()},
        "design": {
            "state_scoring": (
                "exact match of final snapshot to a scenario authorized final "
                "state, plus harness-side state invariants"
            ),
            "claim_verification": (
                "per-turn snapshots (state in force when each claim was "
                "spoken), key-aware together-in-one-subtree matching"
            ),
            "provider_trust": "harness",
            "provider_probe": True,
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _all_records() -> dict[str, list[SavedRunRecord]]:
    # Judges and labels consume the re-graded records when they exist:
    # re-grading applies verifier improvements offline, without re-runs.
    root = OUT / "regraded" if (OUT / "regraded").exists() else OUT / "runs"
    return {label: load_records(root / label) for label in AGENTS}


def phase_judges(concurrency: int) -> None:
    async def judge_model(judge_label: str, spec: ModelSpec, visibility: JudgeVisibility) -> None:
        judge = LLMJudge(build_client(spec), JUDGE_PROMPT, visibility)
        semaphore = asyncio.Semaphore(concurrency)

        async def one(agent_label: str, record: SavedRunRecord) -> None:
            target = (
                OUT
                / "judgements"
                / judge_label
                / visibility.value
                / agent_label
                / f"{record.scenario_id}.r{record.repeat + 1}.json"
            )
            if target.exists():
                return
            async with semaphore:
                judgement = await judge.judge(record.events)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(judgement.model_dump_json(indent=2), encoding="utf-8")

        await asyncio.gather(
            *(
                one(agent_label, record)
                for agent_label, records in _all_records().items()
                for record in records
            )
        )
        print(f"judge {judge_label} / {visibility.value}: done")

    for judge_label, spec in JUDGES.items():
        for visibility in JudgeVisibility:
            asyncio.run(judge_model(judge_label, spec, visibility))


def _reply_texts(record: SavedRunRecord) -> dict[int, tuple[str, str]]:
    """Map reply sequence -> (turn_id, text). Turn id is the preceding turn."""
    replies: dict[int, tuple[str, str]] = {}
    turn = ""
    for event in record.events:
        if event.kind.value == "customer_message":
            turn = event.turn_id
        elif event.kind.value == "agent_reply":
            replies[event.sequence] = (turn, str(event.payload.get("reply", "")))
    return replies


def phase_labels() -> None:
    labels_dir = OUT / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    claim_rows: list[dict[str, object]] = []
    reply_rows: list[dict[str, object]] = []
    run_rows: list[dict[str, object]] = []
    scenarios = {
        s.scenario_id: s for s in discover_scenarios(ROOT / "safeorderbench", domain=Domain.BANKING)
    }
    for agent_label, records in _all_records().items():
        for record in records:
            replies = _reply_texts(record)
            transcript = render_transcript(record.events, JudgeVisibility.WITH_STATE)
            verdicts = {v.claim.claim_id: v for v in record.claim_verdicts}
            for claim in record.claims:
                verdict = verdicts.get(claim.claim_id)
                turn_id, reply_text = replies.get(claim.reply_sequence, ("", ""))
                claim_rows.append(
                    {
                        "claim_key": (
                            f"{agent_label}|{record.scenario_id}"
                            f"|r{record.repeat + 1}|{claim.claim_id}"
                        ),
                        "model": agent_label,
                        "scenario_id": record.scenario_id,
                        "turn_id": turn_id,
                        "reply_sequence": claim.reply_sequence,
                        "reply_text": reply_text,
                        "action": claim.action,
                        "status": claim.status.value,
                        "attributes": json.dumps(claim.attributes, sort_keys=True),
                        "verdict": verdict.verdict.value if verdict else "",
                        "verdict_reason": verdict.reason if verdict else "",
                        "trace_summary": transcript,
                        "label_extraction_correct": "",
                        "label_verdict_correct": "",
                        "notes": "",
                    }
                )
            claims_by_sequence: dict[int, list[str]] = {}
            for claim in record.claims:
                claims_by_sequence.setdefault(claim.reply_sequence, []).append(
                    f"{claim.status.value} {json.dumps(claim.attributes, sort_keys=True)}"
                )
            for sequence, (turn_id, text) in replies.items():
                reply_rows.append(
                    {
                        "reply_key": (
                            f"{agent_label}|{record.scenario_id}"
                            f"|r{record.repeat + 1}|reply-{sequence}"
                        ),
                        "model": agent_label,
                        "scenario_id": record.scenario_id,
                        "turn_id": turn_id,
                        "reply_sequence": sequence,
                        "reply_text": text,
                        "extracted_claims": "; ".join(claims_by_sequence.get(sequence, [])),
                        "parse_error": "",
                        "label_missed_claims": "",
                        "notes": "",
                    }
                )
            scenario = scenarios[record.scenario_id]
            run_rows.append(
                {
                    "run_key": f"{agent_label}|{record.scenario_id}|r{record.repeat + 1}",
                    "model": agent_label,
                    "scenario_id": record.scenario_id,
                    "scenario_description": scenario.description,
                    "trace_summary": transcript,
                    "label_pass": "",
                    "notes": "",
                }
            )
    for name, rows in (("claims", claim_rows), ("replies", reply_rows), ("runs", run_rows)):
        with (labels_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["claim_key"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"labels/{name}.csv: {len(rows)} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("runs", "judges", "labels", "all"), default="all")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    if args.phase in {"runs", "all"}:
        phase_runs(args.repeats, args.concurrency)
    if args.phase in {"judges", "all"}:
        phase_judges(args.concurrency)
    if args.phase in {"labels", "all"}:
        phase_labels()


if __name__ == "__main__":
    main()
