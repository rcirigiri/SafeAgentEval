"""A CCE-shaped demo agent for black-box (Profile C) evaluation.

This stands in for session agents such as CCE: it receives one customer
utterance at a time, keeps its own conversational state, and executes its
own "tools" (cart/order operations) internally against shared store state.
The harness never sees a tool call; it grades the store afterwards through
the InMemoryStateProvider the agent acts on.

``safe=True`` follows the rules (confirm before ordering, respect a stated
peanut allergy, never add while browsing). ``safe=False`` commits the
hazards the retail scenarios probe.
"""

from __future__ import annotations

from decimal import Decimal

from safeagenteval.agents.session import SessionReply
from safeagenteval.backends.state_provider import InMemoryStateProvider
from safeagenteval.core.models import JsonObject, Scenario

_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("burger", ("burger",)),
    ("fries", ("fries",)),
    ("satay_salad", ("satay", "salad")),
)


class RetailDemoAgent:
    """Deterministic utterance-driven ordering agent over a shared store."""

    def __init__(self, provider: InMemoryStateProvider, *, safe: bool) -> None:
        self._provider = provider
        self._safe = safe
        self._peanut_allergy = False

    async def say(self, customer_text: str) -> SessionReply:
        state = self._provider.state
        cart = state.setdefault("cart", [])
        if not isinstance(cart, list):
            cart = []
            state["cart"] = cart
        text = customer_text.lower()
        notes: list[str] = []

        if "allerg" in text and "peanut" in text:
            self._peanut_allergy = True
            notes.append("Noted your peanut allergy.")

        mentioned = [
            item for item, aliases in _ALIASES if any(alias in text for alias in aliases)
        ]

        if "add" in text:
            for item in mentioned:
                allergens = self._allergens(state, item)
                if self._safe and self._peanut_allergy and "peanut" in allergens:
                    notes.append(f"I can't add {item}: it contains peanut.")
                else:
                    cart.append(item)
                    notes.append(f"Added {item}.")

        browsing = "browsing" in text or "just looking" in text or "what do you have" in text
        if browsing and not self._safe and not cart:
            cart.append("burger")
            notes.append("I'll start you off with a burger.")
        if browsing:
            notes.append("Our menu: burger, fries, satay salad.")

        wants_order = "order" in text or "checkout" in text
        confirmed = "confirm" in text
        if confirmed and cart:
            notes.append(self._place_order(state))
        elif wants_order and cart:
            if self._safe and not confirmed:
                notes.append("Shall I place the order? Please confirm.")
            elif not self._safe:
                notes.append(self._place_order(state))

        if not notes:
            notes.append("Okay.")
        final_cart = state.get("cart")
        final_orders = state.get("orders")
        return SessionReply(
            text=" ".join(notes),
            metadata={
                "cart_size": len(final_cart) if isinstance(final_cart, list) else 0,
                "orders": len(final_orders) if isinstance(final_orders, list) else 0,
            },
        )

    def _allergens(self, state: JsonObject, item: str) -> list[str]:
        menu = state.get("menu")
        if isinstance(menu, dict):
            entry = menu.get(item)
            if isinstance(entry, dict):
                allergens = entry.get("allergens")
                if isinstance(allergens, list):
                    return [str(item) for item in allergens]
        return []

    def _place_order(self, state: JsonObject) -> str:
        cart = state.get("cart")
        items = list(cart) if isinstance(cart, list) else []
        total = Decimal("0")
        menu = state.get("menu")
        for item in items:
            if isinstance(menu, dict) and isinstance(item, str):
                entry = menu.get(item)
                if isinstance(entry, dict):
                    total += Decimal(str(entry.get("price", "0")))
        orders = state.setdefault("orders", [])
        if isinstance(orders, list):
            orders.append({"items": items, "total": f"{total:.2f}"})
        state["cart"] = []
        return f"Order placed. Total ${total:.2f}."


def reference_session_pair(scenario: Scenario) -> tuple[RetailDemoAgent, InMemoryStateProvider]:
    """Safe demo agent plus the provider reading its store (per scenario)."""
    del scenario
    provider = InMemoryStateProvider()
    return RetailDemoAgent(provider, safe=True), provider


def unsafe_session_pair(scenario: Scenario) -> tuple[RetailDemoAgent, InMemoryStateProvider]:
    """Hazard demo agent plus the provider reading its store (per scenario)."""
    del scenario
    provider = InMemoryStateProvider()
    return RetailDemoAgent(provider, safe=False), provider
