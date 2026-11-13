"""The ``shared-pack`` command: list and instantiate the policy gates."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from safeagenteval.shared_pack import (
    SLOT_NAMES,
    Pillar,
    instantiate,
    validate_shared_pack,
)


def register(app: typer.Typer) -> None:
    """Register the shared-pack commands on ``app``."""

    @app.command("shared-pack")
    def shared_pack(
        pillar: Annotated[
            str | None,
            typer.Option(help="Only show gates of this pillar (policy|compliance|safety|pii)"),
        ] = None,
        slot: Annotated[
            list[str] | None,
            typer.Option(
                help="Domain slot binding, e.g. --slot COMMIT='transfer funds' (repeatable)"
            ),
        ] = None,
        as_json: Annotated[bool, typer.Option("--json", help="Emit JSON")] = False,
    ) -> None:
        """List the 16 domain-neutral policy gates (POL/CMP/SAF/PII).

        With every slot bound (--slot COMMIT=... --slot PROTECTED=...
        --slot HAZARD=... --slot DATA_SURFACE=...), gate descriptions are
        printed instantiated for that domain.
        """
        gates = validate_shared_pack()
        if pillar is not None:
            try:
                wanted = Pillar(pillar.lower())
            except ValueError:
                raise typer.BadParameter(
                    f"unknown pillar {pillar!r}; use policy|compliance|safety|pii"
                ) from None
            gates = tuple(gate for gate in gates if gate.pillar is wanted)

        bindings: dict[str, str] = {}
        for item in slot or []:
            name, sep, value = item.partition("=")
            if not sep or name.strip() not in SLOT_NAMES:
                raise typer.BadParameter(
                    f"--slot must be NAME=value with NAME in {', '.join(SLOT_NAMES)}"
                )
            bindings[name.strip()] = value
        full = len(bindings) == len(SLOT_NAMES)

        if as_json:
            typer.echo(
                json.dumps(
                    [
                        {
                            "gate_id": gate.gate_id,
                            "pillar": gate.pillar.value,
                            "title": gate.title,
                            "zero_tolerance": gate.zero_tolerance,
                            "mode": gate.mode.value,
                            "category": gate.category.value if gate.category else None,
                            "adversarial": (
                                instantiate(gate.adversarial, bindings)
                                if full
                                else gate.adversarial
                            ),
                            "benign": (instantiate(gate.benign, bindings) if full else gate.benign),
                            "banking_scenarios": list(gate.banking_scenarios),
                        }
                        for gate in gates
                    ],
                    indent=2,
                )
            )
            return

        for gate in gates:
            marker = " [zero-tolerance]" if gate.zero_tolerance else ""
            typer.echo(f"{gate.gate_id} ({gate.pillar.value}) {gate.title}{marker}")
            adversarial = instantiate(gate.adversarial, bindings) if full else gate.adversarial
            benign = instantiate(gate.benign, bindings) if full else gate.benign
            typer.echo(f"  adversarial: {adversarial}")
            typer.echo(f"  benign:      {benign}")
            if gate.banking_scenarios:
                typer.echo(f"  banking:     {', '.join(gate.banking_scenarios)}")
