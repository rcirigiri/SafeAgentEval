"""Banking Backend v2: structurally realistic, deterministic, simulated.

Extends the v1 banking model with a transfer lifecycle
(pending -> settled/returned/failed, cancelled), authorization holds,
derived available balance, account status and bank limits, payee
verification, idempotency keys, per-rail settlement delays and fees, and a
logical clock advanced only through ``tick()``. See
``docs/banking_tier1_design.md``.
"""

from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
from typing import cast

from pydantic import JsonValue

from safeagenteval.backends.banking.migration import migrate_banking_state_v1_to_v2
from safeagenteval.core.models import (
    BackendExecution,
    JsonObject,
    StateChange,
    ToolCall,
    ToolEffect,
    ToolResult,
    ToolSpec,
    ToolStatus,
)

_CENT = Decimal("0.01")
_TERMINAL = {"settled", "returned", "failed", "cancelled"}


def _money(value: Decimal) -> str:
    return f"{value.quantize(_CENT):.2f}"


def _parse(raw: object) -> Decimal | None:
    if not isinstance(raw, str):
        return None
    try:
        value = Decimal(raw.strip())
        cents = value.quantize(_CENT)
    except InvalidOperation:
        return None
    return cents if value.is_finite() and cents == value else None


class BankingBackendV2:
    """Synthetic system of record with a real transfer lifecycle."""

    def __init__(self, initial_state: JsonObject) -> None:
        self._state = migrate_banking_state_v1_to_v2(initial_state)
        raw_tick = self._state.get("as_of_tick", 0)
        self._tick = raw_tick if isinstance(raw_tick, int) else 0
        self._tools = (
            ToolSpec(
                name="lookup_account",
                description="Read one account, incl. balances and holds.",
                effect=ToolEffect.READ,
                input_schema=_account_schema(),
            ),
            ToolSpec(
                name="list_accounts",
                description="List accounts for a customer.",
                effect=ToolEffect.READ,
                input_schema={
                    "type": "object",
                    "properties": {"owner_id": {"type": "string"}},
                    "required": ["owner_id"],
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="list_payees",
                description="List payees owned by the owner of an account.",
                effect=ToolEffect.READ,
                input_schema=_account_schema(),
            ),
            ToolSpec(
                name="list_transfers",
                description="List transfer records sent from an account.",
                effect=ToolEffect.READ,
                input_schema=_account_schema(),
            ),
            ToolSpec(
                name="get_transfer",
                description="Read one transfer record by id.",
                effect=ToolEffect.READ,
                input_schema={
                    "type": "object",
                    "properties": {"transfer_id": {"type": "string"}},
                    "required": ["transfer_id"],
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="initiate_transfer",
                description="Record a transfer instruction; settles per rail delay.",
                effect=ToolEffect.COMMIT,
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_account_id": {"type": "string"},
                        "payee_id": {"type": "string"},
                        "amount": {"type": "string"},
                        "currency": {"type": "string"},
                        "rail": {"type": "string"},
                        "idempotency_key": {"type": "string"},
                        "memo": {"type": "string"},
                    },
                    "required": ["source_account_id", "payee_id", "amount", "currency"],
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="cancel_transfer",
                description="Cancel a pending transfer and release its hold.",
                effect=ToolEffect.COMMIT,
                input_schema={
                    "type": "object",
                    "properties": {"transfer_id": {"type": "string"}},
                    "required": ["transfer_id"],
                    "additionalProperties": False,
                },
            ),
        )

    # -- protocol ---------------------------------------------------------
    @property
    def tools(self) -> tuple[ToolSpec, ...]:
        return self._tools

    def snapshot(self) -> JsonObject:
        state = copy.deepcopy(self._state)
        state["as_of_tick"] = self._tick
        return state

    def normalize_arguments(self, call: ToolCall) -> JsonObject:
        arguments: JsonObject = copy.deepcopy(dict(call.arguments))
        if call.name == "initiate_transfer":
            amount = _parse(arguments.get("amount"))
            if amount is not None:
                arguments["amount"] = _money(amount)
            rail = arguments.get("rail")
            if isinstance(rail, str):
                arguments["rail"] = rail.lower()
            memo = arguments.get("memo")
            if isinstance(memo, str):
                arguments["memo"] = memo.strip()
        return arguments

    def execute(self, call: ToolCall) -> BackendExecution:
        handlers = {
            "lookup_account": self._lookup_account,
            "list_accounts": self._list_accounts,
            "list_payees": self._list_payees,
            "list_transfers": self._list_transfers,
            "get_transfer": self._get_transfer,
            "initiate_transfer": self._initiate_transfer,
            "cancel_transfer": self._cancel_transfer,
        }
        handler = handlers.get(call.name)
        if handler is None:
            return self._fail(call, "unknown_tool")
        return handler(call)

    def tick(self, steps: int = 1) -> tuple[BackendExecution, ...]:
        """Advance logical time; settle or return transfers that come due."""
        executions: list[BackendExecution] = []
        for _ in range(max(0, steps)):
            self._tick += 1
            for transfer in self._transfers():
                if not isinstance(transfer, dict) or transfer.get("status") != "pending":
                    continue
                settle_tick = transfer.get("settle_tick")
                if not isinstance(settle_tick, int) or self._tick < settle_tick:
                    continue
                executions.append(self._settle(transfer))
        return tuple(executions)

    # -- reads ------------------------------------------------------------
    def _account(self, account_id: object) -> JsonObject | None:
        if not isinstance(account_id, str):
            return None
        account = self._mapping("accounts").get(account_id)
        return account if isinstance(account, dict) else None

    def _available(self, account: JsonObject) -> Decimal:
        ledger = _parse(account.get("ledger_balance")) or Decimal("0")
        held = Decimal("0")
        holds = account.get("holds")
        if isinstance(holds, list):
            for hold in holds:
                if isinstance(hold, dict):
                    held += _parse(hold.get("amount")) or Decimal("0")
        return ledger - held

    def _account_view(self, account_id: str, account: JsonObject) -> JsonObject:
        view = copy.deepcopy(account)
        view["account_id"] = account_id
        view["available_balance"] = _money(self._available(account))
        return view

    def _lookup_account(self, call: ToolCall) -> BackendExecution:
        account_id = call.arguments.get("account_id")
        account = self._account(account_id)
        if account is None or not isinstance(account_id, str):
            return self._fail(call, "account_not_found")
        return self._ok(call, {"account": self._account_view(account_id, account)})

    def _list_accounts(self, call: ToolCall) -> BackendExecution:
        owner = call.arguments.get("owner_id")
        accounts = {
            account_id: self._account_view(account_id, account)
            for account_id, account in self._mapping("accounts").items()
            if isinstance(account, dict) and account.get("owner_id") == owner
        }
        return self._ok(call, {"accounts": cast(JsonValue, accounts)})

    def _list_payees(self, call: ToolCall) -> BackendExecution:
        account = self._account(call.arguments.get("account_id"))
        if account is None:
            return self._fail(call, "account_not_found")
        payees: JsonObject = {}
        for payee_id, payee in self._mapping("payees").items():
            if isinstance(payee, dict) and payee.get("owner_id") == account.get("owner_id"):
                view = copy.deepcopy(payee)
                destination = view.get("destination")
                if isinstance(destination, dict):
                    view["destination"] = {
                        "kind": destination.get("kind"),
                        "masked_identifier": destination.get("masked_identifier"),
                    }
                payees[payee_id] = view
        return self._ok(call, {"payees": payees})

    def _list_transfers(self, call: ToolCall) -> BackendExecution:
        account_id = call.arguments.get("account_id")
        if self._account(account_id) is None:
            return self._fail(call, "account_not_found")
        transfers: list[JsonValue] = [
            copy.deepcopy(transfer)
            for transfer in self._transfers()
            if isinstance(transfer, dict) and transfer.get("source_account_id") == account_id
        ]
        return self._ok(call, {"transfers": transfers})

    def _get_transfer(self, call: ToolCall) -> BackendExecution:
        transfer = self._find_transfer(call.arguments.get("transfer_id"))
        if transfer is None:
            return self._fail(call, "transfer_not_found")
        return self._ok(call, {"transfer": copy.deepcopy(transfer)})

    # -- commits ----------------------------------------------------------
    def _initiate_transfer(self, call: ToolCall) -> BackendExecution:
        args = self.normalize_arguments(call)
        source_id, payee_id = args.get("source_account_id"), args.get("payee_id")
        currency, amount = args.get("currency"), _parse(args.get("amount"))
        rail = str(args.get("rail", "internal")).lower()
        if not isinstance(source_id, str) or not isinstance(payee_id, str):
            return self._fail(call, "invalid_arguments")
        if amount is None or amount <= 0:
            return self._fail(call, "invalid_amount")
        key = args.get("idempotency_key")
        if isinstance(key, str):
            for existing in self._transfers():
                if (
                    isinstance(existing, dict)
                    and existing.get("idempotency_key") == key
                    and existing.get("source_account_id") == source_id
                ):
                    return BackendExecution(
                        result=ToolResult(
                            call_id=call.call_id,
                            name=call.name,
                            status=ToolStatus.SUCCEEDED,
                            output={"transfer": copy.deepcopy(existing), "idempotent_replay": True},
                            committed=False,
                        )
                    )
        source = self._account(source_id)
        payee_value = self._mapping("payees").get(payee_id)
        payee = payee_value if isinstance(payee_value, dict) else None
        if source is None:
            return self._fail(call, "account_not_found")
        if payee is None:
            return self._fail(call, "payee_not_found")
        if payee.get("owner_id") != source.get("owner_id"):
            return self._fail(call, "payee_owner_mismatch")
        if payee.get("verification_status") == "blocked":
            return self._fail(call, "payee_blocked")
        status = source.get("status", "active")
        if status == "frozen":
            return self._fail(call, "account_frozen")
        if status != "active":
            return self._fail(call, "account_closed")
        if source.get("currency") != currency:
            return self._fail(call, "currency_mismatch")
        policy = self._policy()
        fees = policy["fee_schedule"]
        fee = _parse(fees.get(rail)) if isinstance(fees, dict) else None
        if fee is None:
            return self._fail(call, "unknown_rail")
        if payee.get("verification_status") == "unverified":
            limit = _parse(payee.get("first_payment_limit"))
            if limit is not None and amount > limit:
                return self._fail(call, "payee_unverified_limit")
        per_tx = _parse(source.get("per_transaction_limit"))
        if per_tx is not None and amount > per_tx:
            return self._fail(call, "limit_exceeded_per_transaction")
        if amount + fee > self._available(source):
            return self._fail(call, "insufficient_available_funds")

        delays = policy["settlement_delay_ticks"]
        raw_delay = delays.get(rail, 0) if isinstance(delays, dict) else 0
        delay = raw_delay if isinstance(raw_delay, int) else 0
        transfer_id = self._next_transfer_id()
        hold_id = f"hold-{transfer_id.removeprefix('transfer-')}"
        transfer: JsonObject = {
            "transfer_id": transfer_id,
            "idempotency_key": key if isinstance(key, str) else call.call_id,
            "source_account_id": source_id,
            "payee_id": payee_id,
            "amount": _money(amount),
            "currency": currency,
            "fee": _money(fee),
            "rail": rail,
            "status": "pending",
            "created_tick": self._tick,
            "settle_tick": self._tick + delay,
            "settled_tick": None,
            "hold_id": hold_id,
            "memo": str(args.get("memo", "")),
            "reversal_of": None,
        }
        changes: list[StateChange] = []
        holds = source.setdefault("holds", [])
        if delay > 0:
            assert isinstance(holds, list)
            hold: JsonObject = {
                "hold_id": hold_id,
                "transfer_id": transfer_id,
                "amount": _money(amount + fee),
                "placed_tick": self._tick,
            }
            changes.append(
                StateChange(
                    path=f"/accounts/{source_id}/holds/{len(holds)}",
                    before=None,
                    after=copy.deepcopy(hold),
                )
            )
            holds.append(hold)
        self._transfers().append(transfer)
        changes.append(
            StateChange(
                path=f"/transfers/{len(self._transfers()) - 1}",
                before=None,
                after=copy.deepcopy(transfer),
            )
        )
        if delay == 0:
            settled = self._settle(transfer, already_recorded=True)
            changes.extend(settled.changes)
            transfer = self._find_transfer(transfer_id) or transfer
        return BackendExecution(
            result=ToolResult(
                call_id=call.call_id,
                name=call.name,
                status=ToolStatus.SUCCEEDED,
                output={"transfer": copy.deepcopy(transfer)},
                committed=True,
            ),
            changes=tuple(changes),
        )

    def _cancel_transfer(self, call: ToolCall) -> BackendExecution:
        transfer = self._find_transfer(call.arguments.get("transfer_id"))
        if transfer is None:
            return self._fail(call, "transfer_not_found")
        if transfer.get("status") != "pending":
            return self._fail(call, "transfer_not_cancellable")
        changes = list(self._release_hold(transfer))
        before = transfer.get("status")
        transfer["status"] = "cancelled"
        transfer["hold_id"] = None
        index = self._transfers().index(transfer)
        changes.append(
            StateChange(path=f"/transfers/{index}/status", before=before, after="cancelled")
        )
        return BackendExecution(
            result=ToolResult(
                call_id=call.call_id,
                name=call.name,
                status=ToolStatus.SUCCEEDED,
                output={"transfer": copy.deepcopy(transfer)},
                committed=True,
            ),
            changes=tuple(changes),
        )

    # -- settlement ---------------------------------------------------------
    def _settle(self, transfer: JsonObject, *, already_recorded: bool = False) -> BackendExecution:
        source_id = str(transfer.get("source_account_id"))
        source = self._account(source_id) or {}
        amount = _parse(transfer.get("amount")) or Decimal("0")
        fee = _parse(transfer.get("fee")) or Decimal("0")
        outcome = self._settlement_outcome(transfer)
        changes: list[StateChange] = list(self._release_hold(transfer))
        index = self._transfers().index(transfer)
        if outcome == "returned":
            transfer["status"] = "returned"
        else:
            ledger = _parse(source.get("ledger_balance")) or Decimal("0")
            new_ledger = ledger - amount - fee
            changes.append(
                StateChange(
                    path=f"/accounts/{source_id}/ledger_balance",
                    before=_money(ledger),
                    after=_money(new_ledger),
                )
            )
            source["ledger_balance"] = _money(new_ledger)
            transfer["status"] = "settled"
            transfer["settled_tick"] = self._tick
        transfer["hold_id"] = None
        changes.append(
            StateChange(
                path=f"/transfers/{index}/status", before="pending", after=transfer["status"]
            )
        )
        return BackendExecution(
            result=ToolResult(
                call_id=f"settlement-{transfer.get('transfer_id')}",
                name="settlement",
                status=ToolStatus.SUCCEEDED,
                output={"transfer": copy.deepcopy(transfer)},
                committed=False,
            ),
            changes=tuple(changes),
        )

    def _settlement_outcome(self, transfer: JsonObject) -> str:
        outcomes = self._state.get("settlement_outcomes")
        if isinstance(outcomes, list):
            for item in outcomes:
                if isinstance(item, dict) and item.get("transfer_id") == transfer.get(
                    "transfer_id"
                ):
                    return str(item.get("outcome", "settled"))
        return "settled"

    def _release_hold(self, transfer: JsonObject) -> tuple[StateChange, ...]:
        hold_id = transfer.get("hold_id")
        source = self._account(transfer.get("source_account_id"))
        if not hold_id or source is None:
            return ()
        holds = source.get("holds")
        if not isinstance(holds, list):
            return ()
        for index, hold in enumerate(holds):
            if isinstance(hold, dict) and hold.get("hold_id") == hold_id:
                del holds[index]
                return (
                    StateChange(
                        path=f"/accounts/{transfer.get('source_account_id')}/holds/{index}",
                        before=copy.deepcopy(hold),
                        after=None,
                    ),
                )
        return ()

    # -- helpers ------------------------------------------------------------
    def _find_transfer(self, transfer_id: object) -> JsonObject | None:
        for transfer in self._transfers():
            if isinstance(transfer, dict) and transfer.get("transfer_id") == transfer_id:
                return transfer
        return None

    def _next_transfer_id(self) -> str:
        highest = 0
        for transfer in self._transfers():
            tid = transfer.get("transfer_id") if isinstance(transfer, dict) else None
            if isinstance(tid, str):
                _, _, number = tid.rpartition("-")
                if number.isdigit():
                    highest = max(highest, int(number))
        return f"transfer-{highest + 1:03d}"

    def _policy(self) -> JsonObject:
        policy = self._state.get("bank_policy")
        return policy if isinstance(policy, dict) else {}

    def _mapping(self, key: str) -> JsonObject:
        value = self._state.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"state field {key!r} must be a mapping")
        return value

    def _transfers(self) -> list[JsonValue]:
        value = self._state.get("transfers")
        if not isinstance(value, list):
            raise ValueError("state field 'transfers' must be a list")
        return value

    @staticmethod
    def _ok(call: ToolCall, output: JsonObject) -> BackendExecution:
        return BackendExecution(
            result=ToolResult(
                call_id=call.call_id, name=call.name, status=ToolStatus.SUCCEEDED, output=output
            )
        )

    @staticmethod
    def _fail(call: ToolCall, code: str) -> BackendExecution:
        return BackendExecution(
            result=ToolResult(
                call_id=call.call_id, name=call.name, status=ToolStatus.FAILED, error=code
            )
        )


def _account_schema() -> JsonObject:
    return {
        "type": "object",
        "properties": {"account_id": {"type": "string"}},
        "required": ["account_id"],
        "additionalProperties": False,
    }
