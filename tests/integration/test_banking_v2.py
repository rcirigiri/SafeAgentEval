"""Backend v2: lifecycle, holds, idempotency, migration, and v2 scenarios."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

from safeagenteval.backends.banking.backend_v2 import BankingBackendV2
from safeagenteval.backends.banking.factory import banking_backend_for
from safeagenteval.backends.banking.migration import migrate_banking_state_v1_to_v2
from safeagenteval.conformance import ConformanceProfile, check_backend
from safeagenteval.core.models import Configuration, ToolCall
from safeagenteval.harness.runner import run_scenario
from safeagenteval.mocks.banking_plans import PlanAgent, plans_for
from safeagenteval.scenarios.loader import load_scenario

ROOT = Path(__file__).parents[2]
BENCHMARK = ROOT / "safeorderbench"


def _v1_state() -> dict[str, object]:
    return {
        "accounts": {
            "account-checking": {
                "owner_id": "customer-001",
                "currency": "USD",
                "balance": "2000.00",
            }
        },
        "payees": {
            "payee-alice": {
                "owner_id": "customer-001",
                "display_name": "Alice",
                "destination_account_ref": "destination-alice",
            }
        },
        "transfers": [],
    }


def _transfer(call_id: str, rail: str = "ach", key: str | None = None) -> ToolCall:
    arguments: dict[str, str] = {
        "source_account_id": "account-checking",
        "payee_id": "payee-alice",
        "amount": "100.00",
        "currency": "USD",
        "rail": rail,
    }
    if key:
        arguments["idempotency_key"] = key
    return ToolCall(call_id=call_id, name="initiate_transfer", arguments=arguments)


def test_migration_upconverts_v1_state() -> None:
    migrated = migrate_banking_state_v1_to_v2(_v1_state())  # type: ignore[arg-type]
    account = migrated["accounts"]["account-checking"]  # type: ignore[index]
    assert account["ledger_balance"] == "2000.00"
    assert "balance" not in account
    assert migrate_banking_state_v1_to_v2(migrated) == migrated  # idempotent


def test_pending_holds_then_settles_on_tick() -> None:
    backend = BankingBackendV2(_v1_state())  # type: ignore[arg-type]
    execution = backend.execute(_transfer("t1"))
    assert execution.result.committed is True
    transfer = execution.result.output["transfer"]
    assert isinstance(transfer, dict) and transfer["status"] == "pending"
    account = backend.snapshot()["accounts"]["account-checking"]  # type: ignore[index]
    assert account["ledger_balance"] == "2000.00"  # not yet posted
    assert account["holds"], "a hold must back the pending transfer"

    backend.tick(48)
    account = backend.snapshot()["accounts"]["account-checking"]  # type: ignore[index]
    assert account["ledger_balance"] == "1900.00"
    assert account["holds"] == []
    transfers = backend.snapshot()["transfers"]  # type: ignore[index]
    assert isinstance(transfers, list) and transfers[0]["status"] == "settled"


def test_idempotency_and_frozen_account() -> None:
    backend = BankingBackendV2(_v1_state())  # type: ignore[arg-type]
    backend.execute(_transfer("t1", key="k-1"))
    after_first = backend.snapshot()
    replay = backend.execute(_transfer("t2", key="k-1"))
    assert replay.result.committed is False
    assert replay.result.output.get("idempotent_replay") is True
    assert backend.snapshot() == after_first

    frozen_state = copy.deepcopy(_v1_state())
    frozen_state["accounts"]["account-checking"]["status"] = "frozen"  # type: ignore[index]
    frozen = BankingBackendV2(frozen_state)  # type: ignore[arg-type]
    refused = frozen.execute(_transfer("t3"))
    assert refused.result.status.value == "failed"
    assert refused.result.error == "account_frozen"


def test_v2_backend_passes_full_conformance() -> None:
    report = check_backend(
        lambda: BankingBackendV2(_v1_state()),  # type: ignore[arg-type]
        profile=ConformanceProfile.FULL,
        probe_calls=(
            ToolCall(
                call_id="p1", name="list_payees", arguments={"account_id": "account-checking"}
            ),
        ),
    )
    assert report.passed, [c.model_dump() for c in report.checks if not c.passed]


def test_v2_scenarios_with_scripted_plans() -> None:
    for relative in (
        "public/banking_v2/partial_failure/pending_settlement_001.yaml",
        "public/banking_v2/duplicate_transaction/idempotent_retry_001.yaml",
    ):
        scenario = load_scenario(BENCHMARK / relative, BENCHMARK)
        assert isinstance(banking_backend_for(scenario), BankingBackendV2)
        result = asyncio.run(
            run_scenario(
                scenario,
                PlanAgent(plans_for(scenario).safe),
                banking_backend_for(scenario),
                Configuration.C2,
            )
        )
        assert result.completed
        assert result.state_score.final_state_correct, result.final_state
        assert result.state_score.violations == ()
        assert result.state_score.successful_commits == 1


def test_v2_unsafe_unkeyed_retry_duplicates() -> None:
    scenario = load_scenario(
        BENCHMARK / "public/banking_v2/duplicate_transaction/idempotent_retry_001.yaml",
        BENCHMARK,
    )
    result = asyncio.run(
        run_scenario(
            scenario,
            PlanAgent(plans_for(scenario).unsafe),
            banking_backend_for(scenario),
            Configuration.C0,
        )
    )
    assert not result.state_score.final_state_correct
    assert result.state_score.successful_commits == 2
