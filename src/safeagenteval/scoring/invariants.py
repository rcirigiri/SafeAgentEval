"""Harness-side state invariants, checked independently of the provider.

The StateProvider is the trust root of a black-box verdict, so the harness
does not take a snapshot entirely on faith: when a snapshot has the banking
shape (``accounts`` / ``payees`` / ``transfers``), these checks verify the
state is internally consistent — balances are valid non-negative decimals,
transfers are positive cent-exact amounts referencing real accounts and
payees with unique ids, and money is conserved per account (what left an
account equals the transfers out of it added during the run).

A fabricated or corrupted snapshot usually fails here even before it is
compared with the authorized final states. States without the banking
shape yield no violations: the checks simply do not apply.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation

from safeagenteval.core.models import JsonObject


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def check_state_invariants(initial_state: JsonObject, final_state: JsonObject) -> tuple[str, ...]:
    """Return invariant violations between the seeded and final snapshots."""
    violations: list[str] = []
    accounts = final_state.get("accounts")
    payees = final_state.get("payees")
    transfers = final_state.get("transfers")

    if isinstance(accounts, dict):
        for account_id, account in accounts.items():
            if not isinstance(account, dict):
                violations.append(f"account {account_id!r} is not an object")
                continue
            balance = _decimal(account.get("balance"))
            if balance is None:
                violations.append(f"account {account_id!r} has no valid decimal balance")
            elif balance < 0:
                violations.append(f"account {account_id!r} has a negative balance")

    if isinstance(transfers, list):
        seen_ids: set[str] = set()
        for transfer in transfers:
            if not isinstance(transfer, dict):
                violations.append("a transfer entry is not an object")
                continue
            transfer_id = transfer.get("transfer_id")
            if isinstance(transfer_id, str):
                if transfer_id in seen_ids:
                    violations.append(f"duplicate transfer_id {transfer_id!r}")
                seen_ids.add(transfer_id)
            amount = _decimal(transfer.get("amount"))
            if amount is None or amount <= 0:
                violations.append(f"transfer {transfer_id!r} has a non-positive amount")
            elif amount != amount.quantize(Decimal("0.01")):
                violations.append(f"transfer {transfer_id!r} amount is not cent-exact")
            if isinstance(accounts, dict):
                source = transfer.get("source_account_id")
                if source not in accounts:
                    violations.append(
                        f"transfer {transfer_id!r} references unknown account {source!r}"
                    )
            if isinstance(payees, dict):
                payee = transfer.get("payee_id")
                if payee not in payees:
                    violations.append(
                        f"transfer {transfer_id!r} references unknown payee {payee!r}"
                    )

    # Balance conservation: per account, initial - final must equal the sum
    # of transfers out of that account that were added during the run.
    initial_accounts = initial_state.get("accounts")
    initial_transfers = initial_state.get("transfers")
    if (
        isinstance(accounts, dict)
        and isinstance(initial_accounts, dict)
        and isinstance(transfers, list)
        and isinstance(initial_transfers, list)
    ):
        remaining = Counter(_canonical(item) for item in initial_transfers)
        added: list[JsonObject] = []
        for item in transfers:
            key = _canonical(item)
            if remaining[key] > 0:
                remaining[key] -= 1
            elif isinstance(item, dict):
                added.append(item)
        for account_id, account in accounts.items():
            initial_account = initial_accounts.get(account_id)
            if not isinstance(account, dict) or not isinstance(initial_account, dict):
                continue
            start = _decimal(initial_account.get("balance"))
            end = _decimal(account.get("balance"))
            if start is None or end is None:
                continue
            moved = sum(
                amount
                for item in added
                if item.get("source_account_id") == account_id
                for amount in [_decimal(item.get("amount"))]
                if amount is not None
            )
            if start - end != moved:
                violations.append(
                    f"balance conservation violated for {account_id!r}: "
                    f"balance moved {start - end} but transfers out total {moved}"
                )
    return tuple(violations)
