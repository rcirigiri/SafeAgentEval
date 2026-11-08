"""Adoption surface: CLI commands, conformance checks, and HTML reporting."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from safeagenteval.backends.banking.backend import BankingBackend
from safeagenteval.cli import app
from safeagenteval.conformance import ConformanceProfile, check_backend
from safeagenteval.core.models import Domain, ToolCall
from safeagenteval.scenarios.loader import discover_scenarios

ROOT = Path(__file__).parents[2]
BENCHMARK = ROOT / "safeorderbench"
BENIGN = BENCHMARK / "public/banking/prompt_injection/payee_note_benign_001.yaml"

runner = CliRunner()


def _state() -> dict[str, object]:
    return {
        "accounts": {
            "account-checking": {
                "owner_id": "customer-001",
                "currency": "USD",
                "balance": "2000.00",
            }
        },
        "payees": {
            "payee-alice": {"owner_id": "customer-001", "display_name": "Alice"},
        },
        "transfers": [],
    }


def test_banking_backend_passes_lite_conformance() -> None:
    probes = (
        ToolCall(call_id="p1", name="list_payees", arguments={"account_id": "account-checking"}),
    )
    report = check_backend(
        lambda: BankingBackend(_state()), profile=ConformanceProfile.LITE, probe_calls=probes
    )
    assert report.passed, [c.model_dump() for c in report.checks if not c.passed]
    assert report.passed_count >= 8


def test_full_profile_requires_tick() -> None:
    report = check_backend(lambda: BankingBackend(_state()), profile=ConformanceProfile.FULL)
    assert not report.passed  # v1 backend has no tick(); full must say so, not crash


def test_cli_explain_and_lint() -> None:
    explained = runner.invoke(app, ["explain-scenario", str(BENIGN)])
    assert explained.exit_code == 0, explained.output
    assert "1900.00" in explained.output
    linted = runner.invoke(app, ["lint-scenario", str(BENIGN)])
    assert linted.exit_code == 0, linted.output
    assert "OK:" in linted.output


def test_cli_run_report_view(tmp_path: Path) -> None:
    out = tmp_path / "runs"
    ran = runner.invoke(
        app,
        [
            "run",
            "--agent",
            "session-reference",
            "--scenario",
            "retail.confirmation_gate.benign_order_001",
            "--out",
            str(out),
        ],
    )
    assert ran.exit_code == 0, ran.output
    records = list(out.glob("*.json"))
    assert len(records) == 1

    reported = runner.invoke(app, ["report", str(out)])
    assert reported.exit_code == 0, reported.output
    assert "benign_order_001" in reported.output

    html_out = tmp_path / "trace.html"
    viewed = runner.invoke(app, ["view", str(records[0]), "--out", str(html_out)])
    assert viewed.exit_code == 0, viewed.output
    assert "benign_order_001" in html_out.read_text(encoding="utf-8")


def test_discover_scenarios_excludes_versioned_by_default() -> None:
    default_ids = {s.scenario_id for s in discover_scenarios(BENCHMARK, domain=Domain.BANKING)}
    versioned_ids = {
        s.scenario_id
        for s in discover_scenarios(BENCHMARK, domain=Domain.BANKING, include_versioned=True)
    }
    assert len(default_ids) == 14
    assert "banking.duplicate_transaction.idempotent_retry_001" in versioned_ids
    assert versioned_ids > default_ids


def test_cli_run_accepts_scenario_yaml_path(tmp_path: Path) -> None:
    retail_scenario = BENCHMARK / "public/retail/confirmation_gate/benign_order_001.yaml"
    out = tmp_path / "runs"
    ran = runner.invoke(
        app,
        [
            "run",
            "--agent",
            "session-reference",
            "--scenario",
            str(retail_scenario),
            "--out",
            str(out),
        ],
    )
    assert ran.exit_code == 0, ran.output
    assert len(list(out.glob("*.json"))) == 1


def test_cli_rejects_mediated_mode(tmp_path: Path) -> None:
    # Mediated agents and mediated scenarios were removed from the CLI in
    # the black-box focus; both must fail with guidance, not silently run.
    mediated_agent = runner.invoke(
        app,
        ["run", "--agent", "reference", "--out", str(tmp_path / "a")],
    )
    assert mediated_agent.exit_code == 2, mediated_agent.output
    mediated_scenario = runner.invoke(
        app,
        [
            "run",
            "--domain",
            "banking",
            "--agent",
            "session-reference",
            "--scenario",
            "banking.prompt_injection.payee_note_benign_001",
            "--out",
            str(tmp_path / "b"),
        ],
    )
    assert mediated_scenario.exit_code == 2, mediated_scenario.output


def test_http_agent_adapter_round_trip() -> None:
    import asyncio
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from safeagenteval.agents.http_adapter import HttpAgentAdapter
    from safeagenteval.core.models import Message, Role

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            body = json.dumps({"reply": "hello from remote agent"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        adapter = HttpAgentAdapter(f"http://127.0.0.1:{server.server_port}/respond")
        turn = asyncio.run(
            adapter.respond([Message(role=Role.CUSTOMER, content="hi", turn_id="t")], [])
        )
        assert turn.reply == "hello from remote agent"
    finally:
        server.shutdown()


def test_cli_build_site(tmp_path: Path) -> None:
    out = tmp_path / "runs"
    ran = runner.invoke(
        app,
        [
            "run",
            "--agent",
            "session-reference",
            "--scenario",
            "retail.confirmation_gate.benign_order_001",
            "--out",
            str(out),
        ],
    )
    assert ran.exit_code == 0, ran.output
    site = tmp_path / "site" / "index.html"
    built = runner.invoke(app, ["build-site", str(out), "--out", str(site)])
    assert built.exit_code == 0, built.output
    assert "Pass rate" in site.read_text(encoding="utf-8")


def test_plugin_spec_passthrough() -> None:
    from safeagenteval.plugins import resolve_backend_spec

    assert resolve_backend_spec("some.module:Backend") == "some.module:Backend"


def test_cli_new_session_agent(tmp_path: Path) -> None:
    result = runner.invoke(app, ["new-session-agent", "myshop", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "myshop" / "myshop" / "agent.py").exists()
    assert (tmp_path / "myshop" / "README.md").exists()
