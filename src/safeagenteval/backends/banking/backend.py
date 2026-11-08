"""Deterministic banking and payments backend."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation

from pydantic import JsonValue

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


class BankingBackend:
    """Synthetic system of record for banking scenarios."""

    def __init__(self, initial_state: JsonObject) -> None:
        self._state = deepcopy(initial_state)
        self._tools = (
            ToolSpec(
                name="lookup_account",
                description="Read one account by id.",
                effect=ToolEffect.READ,
                input_schema=_account_id_schema(),
            ),
            ToolSpec(
                name="list_payees",
                description="List payees owned by the owner of an account.",
                effect=ToolEffect.READ,
                input_schema=_account_id_schema(),
            ),
            ToolSpec(
                name="list_transfers",
                description="List transfers sent from an account.",
                effect=ToolEffect.READ,
                input_schema=_account_id_schema(),
            ),
            ToolSpec(
                name="initiate_transfer",
                description="Commit a transfer to an existing payee.",
                effect=ToolEffect.COMMIT,
                input_schema={
                    "type": "object",
                    "properties": {
                        "source_account_id": {"type": "string"},
                        "payee_id": {"type": "string"},
                        "amount": {"type": "string"},
                        "currency": {"type": "string"},
                    },
                    "required": [
                        "source_account_id",
                        "payee_id",
                        "amount",
                        "currency",
                    ],
                    "additionalProperties": False,
                },
            ),
        )

    @property
    def tools(self) -> tuple[ToolSpec, ...]:
        """Return banking tool definitions."""
        return self._tools

    def normalize_arguments(self, call: ToolCall) -> JsonObject:
        """Canonicalize representation-only differences in banking arguments."""
        arguments: JsonObject = deepcopy(dict(call.arguments))
        if call.name == "initiate_transfer":
            amount = _parse_amount(arguments.get("amount"))
            if amount is not None:
                arguments["amount"] = f"{amount:.2f}"
        return arguments

    def snapshot(self) -> JsonObject:
        """Return an isolated state snapshot."""
        return deepcopy(self._state)

    def execute(self, call: ToolCall) -> BackendExecution:
        """Execute one deterministic banking tool request."""
        if call.name == "lookup_account":
            return self._lookup_account(call)
        if call.name == "list_payees":
            return self._list_payees(call)
        if call.name == "list_transfers":
            return self._list_transfers(call)
        if call.name == "initiate_transfer":
            return self._initiate_transfer(call)
        return self._failure(call, f"unknown tool: {call.name}")

    def _lookup_account(self, call: ToolCall) -> BackendExecution:
        account = self._account_for(call)
        if account is None:
            return self._failure(call, "account not found")
        return self._success(call, {"account": deepcopy(account)})

    def _list_payees(self, call: ToolCall) -> BackendExecution:
        account = self._account_for(call)
        if account is None:
            return self._failure(call, "account not found")
        payees: JsonObject = {
            payee_id: deepcopy(payee)
            for payee_id, payee in self._mapping("payees").items()
            if isinstance(payee, dict) and payee.get("owner_id") == account.get("owner_id")
        }
        return self._success(call, {"payees": payees})

    def _list_transfers(self, call: ToolCall) -> BackendExecution:
        account = self._account_for(call)
        if account is None:
            return self._failure(call, "account not found")
        account_id = call.arguments["account_id"]
        transfers: list[JsonValue] = [
            deepcopy(transfer)
            for transfer in self._transfers()
            if isinstance(transfer, dict) and transfer.get("source_account_id") == account_id
        ]
        return self._success(call, {"transfers": transfers})

    def _account_for(self, call: ToolCall) -> JsonObject | None:
        account_id = call.arguments.get("account_id")
        if not isinstance(account_id, str):
            return None
        account = self._mapping("accounts").get(account_id)
        return account if isinstance(account, dict) else None

    def _initiate_transfer(self, call: ToolCall) -> BackendExecution:
        source_id = call.arguments.get("source_account_id")
        payee_id = call.arguments.get("payee_id")
        currency = call.arguments.get("currency")
        amount_raw = call.arguments.get("amount")
        if (
            not isinstance(source_id, str)
            or not isinstance(payee_id, str)
            or not isinstance(currency, str)
        ):
            return self._failure(call, "source account, payee, and currency are required")
        if not isinstance(amount_raw, str):
            return self._failure(call, "amount must be a decimal string")

        amount = _parse_amount(amount_raw)
        if amount is None:
            return self._failure(call, "invalid amount")
        if amount <= 0:
            return self._failure(call, "amount must be positive")

        accounts = self._mapping("accounts")
        payees = self._mapping("payees")
        source = accounts.get(source_id)
        payee = payees.get(payee_id)
        if not isinstance(source, dict):
            return self._failure(call, "source account not found")
        if not isinstance(payee, dict):
            return self._failure(call, "payee not found")
        if payee.get("owner_id") != source.get("owner_id"):
            return self._failure(call, "payee does not belong to the account owner")

        account_currency = source.get("currency")
        if account_currency != currency:
            return self._failure(call, "currency mismatch")
        balance_raw = source.get("balance")
        balance = _parse_amount(balance_raw)
        if balance is None:
            return self._failure(call, "invalid account balance")
        if balance < amount:
            return self._failure(call, "insufficient funds")

        transfer_id = self._next_transfer_id()
        new_balance = (balance - amount).quantize(_CENT)
        transfer: JsonObject = {
            "transfer_id": transfer_id,
            "source_account_id": source_id,
            "payee_id": payee_id,
            "amount": f"{amount:.2f}",
            "currency": currency,
            "status": "completed",
        }
        source["balance"] = f"{new_balance:.2f}"
        self._transfers().append(transfer)

        return BackendExecution(
            result=ToolResult(
                call_id=call.call_id,
                name=call.name,
                status=ToolStatus.SUCCEEDED,
                output={"transfer": deepcopy(transfer)},
                committed=True,
            ),
            changes=(
                StateChange(
                    path=f"/accounts/{source_id}/balance",
                    before=f"{balance:.2f}",
                    after=f"{new_balance:.2f}",
                ),
                StateChange(
                    path=f"/transfers/{len(self._transfers()) - 1}",
                    before=None,
                    after=deepcopy(transfer),
                ),
            ),
        )

    def _next_transfer_id(self) -> str:
        highest = 0
        for transfer in self._transfers():
            transfer_id = transfer.get("transfer_id") if isinstance(transfer, dict) else None
            if isinstance(transfer_id, str):
                prefix, _, number = transfer_id.rpartition("-")
                if prefix == "transfer" and number.isdigit():
                    highest = max(highest, int(number))
        return f"transfer-{highest + 1:03d}"

    def _mapping(self, key: str) -> JsonObject:
        value = self._state.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"initial state field {key!r} must be a mapping")
        return value

    def _transfers(self) -> list[JsonValue]:
        value = self._state.get("transfers")
        if not isinstance(value, list):
            raise ValueError("initial state field 'transfers' must be a list")
        return value

    @staticmethod
    def _success(call: ToolCall, output: JsonObject) -> BackendExecution:
        return BackendExecution(
            result=ToolResult(
                call_id=call.call_id,
                name=call.name,
                status=ToolStatus.SUCCEEDED,
                output=output,
            )
        )

    @staticmethod
    def _failure(call: ToolCall, error: str) -> BackendExecution:
        return BackendExecution(
            result=ToolResult(
                call_id=call.call_id,
                name=call.name,
                status=ToolStatus.FAILED,
                error=error,
            )
        )


def _account_id_schema() -> JsonObject:
    return {
        "type": "object",
        "properties": {"account_id": {"type": "string"}},
        "required": ["account_id"],
        "additionalProperties": False,
    }


def _parse_amount(raw: object) -> Decimal | None:
    """Parse a finite decimal string that is an exact number of cents.

    Sub-cent values such as ``"100.005"`` are rejected, not rounded: rounding
    would change the amount's meaning and let it match a different intent.
    """
    if not isinstance(raw, str):
        return None
    try:
        value = Decimal(raw.strip())
        if not value.is_finite():
            return None
        cents = value.quantize(_CENT)
    except InvalidOperation:
        return None
    return cents if cents == value else None
