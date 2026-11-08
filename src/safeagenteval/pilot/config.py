"""Pilot experiment configuration and on-disk layout."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import yaml
from pydantic import Field, model_validator

from safeagenteval.agents.providers import ModelSpec
from safeagenteval.core.models import Configuration, Domain, FrozenModel, JsonObject, Scenario
from safeagenteval.judges.transcript import JudgeVisibility

SESSION_PLACEHOLDER = "{{SESSION_CONTEXT}}"


class PilotConfig(FrozenModel):
    """Everything that defines one pilot run; versioned alongside its outputs."""

    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    output_dir: Path
    benchmark_root: Path = Path("safeorderbench")
    domain: Domain = Domain.BANKING
    session_customer_id: str
    configurations: tuple[Configuration, ...] = (Configuration.C0, Configuration.C2)
    max_agent_steps_per_customer_turn: int = Field(default=8, ge=1)
    agent_prompt: Path
    extractor_prompt: Path
    models: tuple[ModelSpec, ...] = Field(min_length=1)
    extractor: ModelSpec
    judge_prompt: Path | None = None
    judges: tuple[ModelSpec, ...] = ()
    judge_visibilities: tuple[JudgeVisibility, ...] = tuple(JudgeVisibility)

    @model_validator(mode="after")
    def _check(self) -> PilotConfig:
        names = [model.name for model in self.models]
        if len(names) != len(set(names)):
            raise ValueError("model names must be unique")
        judge_names = [judge.name for judge in self.judges]
        if len(judge_names) != len(set(judge_names)):
            raise ValueError("judge names must be unique")
        if self.judges and self.judge_prompt is None:
            raise ValueError("judges require judge_prompt")
        unsupported = set(self.configurations) - {Configuration.C0, Configuration.C2}
        if unsupported:
            raise ValueError(f"unsupported configurations: {sorted(c.value for c in unsupported)}")
        return self

    def model(self, name: str) -> ModelSpec:
        """Return the model spec called ``name``."""
        for model in self.models:
            if model.name == name:
                return model
        raise KeyError(name)

    def judge(self, name: str) -> ModelSpec:
        """Return the judge spec called ``name``."""
        for judge in self.judges:
            if judge.name == name:
                return judge
        raise KeyError(name)


def load_config(path: Path, root: Path | None = None) -> PilotConfig:
    """Load a pilot config; relative paths resolve against ``root`` (default: cwd)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping")
    base = root or Path.cwd()
    for key in ("output_dir", "benchmark_root", "agent_prompt", "extractor_prompt", "judge_prompt"):
        if key in raw:
            raw[key] = str(base / raw[key])
    return PilotConfig.model_validate(raw)


def load_env_file(path: Path) -> list[str]:
    """Set unset environment variables from a ``KEY=value`` file; return the names set.

    Variables already in the environment win, so a shell export overrides the file.
    """
    if not path.exists():
        return []
    loaded: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if name and value and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded


def sha256_text(text: str) -> str:
    """Hash prompt text so the manifest pins the exact prompt used."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def session_context(scenario: Scenario, customer_id: str) -> str:
    """Describe the authenticated session as a deployment would supply it."""
    accounts = scenario.initial_state.get("accounts")
    owned = (
        sorted(
            f"{account_id} ({account.get('currency', '?')})"
            for account_id, account in accounts.items()
            if isinstance(account, dict) and account.get("owner_id") == customer_id
        )
        if isinstance(accounts, dict)
        else []
    )
    return (
        f"- Authenticated customer: {customer_id}\n"
        f"- The customer's accounts: {', '.join(owned) if owned else 'none'}"
    )


def agent_system_prompt(template: str, scenario: Scenario, customer_id: str) -> str:
    """Fill the agent prompt template for one scenario."""
    if SESSION_PLACEHOLDER not in template:
        raise ValueError(f"agent prompt must contain {SESSION_PLACEHOLDER}")
    return template.replace(SESSION_PLACEHOLDER, session_context(scenario, customer_id))


def extractor_reference(initial_state: JsonObject) -> str:
    """List payee and account identifiers a reply may refer to by name."""
    lines: list[str] = []
    payees = initial_state.get("payees")
    if isinstance(payees, dict):
        for payee_id, payee in sorted(payees.items()):
            if isinstance(payee, dict):
                lines.append(f"- payee {payee_id}: {payee.get('display_name', '')}")
    accounts = initial_state.get("accounts")
    if isinstance(accounts, dict):
        lines.extend(f"- account {account_id}" for account_id in sorted(accounts))
    return "\n".join(lines) if lines else "(none)"


class RunPaths:
    """File layout under ``output_dir``; one JSON file per run."""

    def __init__(self, config: PilotConfig) -> None:
        self.root = config.output_dir

    @property
    def manifest(self) -> Path:
        """Experiment manifest written before any run."""
        return self.root / "manifest.json"

    def run(self, model: str, configuration: Configuration, scenario_id: str) -> Path:
        """Saved trace and usage for one run."""
        return self.root / "runs" / model / configuration.value / f"{scenario_id}.json"

    def claims(self, model: str, configuration: Configuration, scenario_id: str) -> Path:
        """Extracted claims and verdicts for one run."""
        return self.root / "claims" / model / configuration.value / f"{scenario_id}.json"

    def judgement(
        self,
        judge: str,
        visibility: JudgeVisibility,
        model: str,
        configuration: Configuration,
        scenario_id: str,
    ) -> Path:
        """One judge's verdict on one run at one visibility level."""
        return (
            self.root
            / "judgements"
            / judge
            / visibility.value
            / model
            / configuration.value
            / f"{scenario_id}.json"
        )

    @property
    def labels(self) -> Path:
        """Directory holding the hand-labeling CSV files."""
        return self.root / "labels"
