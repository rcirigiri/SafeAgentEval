"""In-memory upconversion of v1 banking states to the v2 schema.

Published v1 files are never rewritten. The v2 backend (and tests that need
the canonical shape) call these functions at load time.
"""

from __future__ import annotations

import copy

from safeagenteval.core.models import JsonObject


def migrate_banking_state_v1_to_v2(state: JsonObject) -> JsonObject:
    """Return the canonical v2 form of a v1 (or already-v2) banking state."""
    result: JsonObject = copy.deepcopy(state)
    if result.get("schema_version") == 2:
        return result
    result["schema_version"] = 2
    result.setdefault("as_of_tick", 0)
    result.setdefault(
        "bank_policy",
        {
            "settlement_delay_ticks": {"internal": 0, "ach": 48, "rtp": 0, "wire": 24},
            "fee_schedule": {"internal": "0.00", "ach": "0.00", "rtp": "0.25", "wire": "15.00"},
        },
    )
    accounts = result.get("accounts")
    if isinstance(accounts, dict):
        for account in accounts.values():
            if isinstance(account, dict):
                if "ledger_balance" not in account and "balance" in account:
                    account["ledger_balance"] = account.pop("balance")
                account.setdefault("type", "checking")
                account.setdefault("status", "active")
                account.setdefault("holds", [])
    payees = result.get("payees")
    if isinstance(payees, dict):
        for payee in payees.values():
            if isinstance(payee, dict):
                payee.setdefault("verification_status", "verified")
                if "destination" not in payee:
                    payee["destination"] = {
                        "kind": "external_account",
                        "masked_identifier": str(payee.get("destination_account_ref", "")),
                    }
    transfers = result.get("transfers")
    if isinstance(transfers, list):
        for transfer in transfers:
            if isinstance(transfer, dict):
                if transfer.get("status") == "completed":
                    transfer["status"] = "settled"
                transfer.setdefault("fee", "0.00")
                transfer.setdefault("rail", "internal")
    return result
