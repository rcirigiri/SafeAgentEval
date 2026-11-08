"""Post-hoc claim extraction and verification over saved runs.

Extraction runs after the agent runs, from the saved replies, so an extractor
failure never aborts or alters an agent run, and claims can be re-extracted
with a new prompt without re-running models.
"""

from __future__ import annotations

from collections.abc import Callable

from safeagenteval.agents.chat import ChatClient
from safeagenteval.agents.providers import ModelSpec, build_client
from safeagenteval.claims.llm_extractor import ExtractionRecord, LLMClaimExtractor
from safeagenteval.claims.verifier import ActionClaim, ClaimVerdict, verify_claims
from safeagenteval.core.models import Configuration, FrozenModel, JsonObject
from safeagenteval.pilot.config import PilotConfig, RunPaths, extractor_reference, sha256_text
from safeagenteval.pilot.runner import RunSummary, load_run
from safeagenteval.trace.recorder import EventKind

ClientFactory = Callable[[ModelSpec], ChatClient]


class ClaimFile(FrozenModel):
    """Extracted claims and deterministic verdicts for one run."""

    model: str
    configuration: Configuration
    scenario_id: str
    extractor: ModelSpec
    extractor_prompt_sha256: str
    records: tuple[ExtractionRecord, ...]
    verdicts: tuple[ClaimVerdict, ...]


async def extract_pilot(
    config: PilotConfig,
    *,
    client_factory: ClientFactory = build_client,
    progress: Callable[[str], None] = print,
) -> RunSummary:
    """Extract and verify claims for every saved run that has no claim file."""
    paths = RunPaths(config)
    prompt = config.extractor_prompt.read_text(encoding="utf-8")
    prompt_hash = sha256_text(prompt)
    client: ChatClient | None = None
    completed = skipped = 0
    failures: list[str] = []

    for run_path in sorted((paths.root / "runs").glob("*/*/*.json")):
        saved = load_run(run_path)
        model = saved.model.name
        scenario_id = saved.result.scenario_id
        target = paths.claims(model, saved.configuration, scenario_id)
        label = f"{model}/{saved.configuration.value}/{scenario_id}"
        if target.exists():
            skipped += 1
            continue
        if client is None:
            client = client_factory(config.extractor)

        events = saved.result.events
        initial = events[0].payload.get("initial_state") if events else None
        reference = extractor_reference(initial if isinstance(initial, dict) else _empty())
        extractor = LLMClaimExtractor(client, prompt, reference)
        claims: list[ActionClaim] = []
        try:
            for event in events:
                if event.kind is EventKind.AGENT_REPLY:
                    reply = str(event.payload.get("reply", ""))
                    claims.extend(await extractor.extract(reply, event.sequence, event.turn_id))
        except Exception as error:  # noqa: BLE001 - retried on the next invocation
            failures.append(f"{label}: {type(error).__name__}: {error}")
            progress(f"extractor API failure, will retry next time: {label}: {error}")
            continue

        claim_file = ClaimFile(
            model=model,
            configuration=saved.configuration,
            scenario_id=scenario_id,
            extractor=config.extractor,
            extractor_prompt_sha256=prompt_hash,
            records=tuple(extractor.records),
            verdicts=verify_claims(claims, events),
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(claim_file.model_dump_json(indent=2), encoding="utf-8")
        completed += 1
        contradicted = sum(v.verdict.value == "contradicted" for v in claim_file.verdicts)
        progress(f"claims {label}: {len(claims)} extracted, {contradicted} contradicted")
    return RunSummary(completed=completed, skipped=skipped, api_failures=tuple(failures))


def _empty() -> JsonObject:
    return {}
