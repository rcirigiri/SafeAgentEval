"""Select the banking backend matching a scenario's state schema."""

from __future__ import annotations

from safeagenteval.backends.banking.backend import BankingBackend
from safeagenteval.backends.banking.backend_v2 import BankingBackendV2
from safeagenteval.backends.base import DomainBackend
from safeagenteval.core.models import Scenario


def banking_backend_for(scenario: Scenario) -> DomainBackend:
    """Return Backend v2 for schema-2 scenarios, v1 otherwise."""
    if scenario.schema_version >= 2 or scenario.initial_state.get("schema_version") == 2:
        return BankingBackendV2(scenario.initial_state)
    return BankingBackend(scenario.initial_state)
