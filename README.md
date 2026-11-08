# SafeAgentEval

SafeAgentEval is a state-aware evaluation harness for tool-using AI agents. It
records agent replies, tool calls, arguments, results, and backend state changes,
then evaluates both:

1. whether the resulting state was authorized; and
2. whether the agent's verifiable statements match the recorded trace.

SafeOrderBench is the companion scenario set used to exercise the harness across
banking, pharmacy, retail, and travel workflows.

> **Status:** Pre-release research software (v0.1.0). The harness, a
> 14-scenario banking seed set for SafeOrderBench, scripted-agent validation,
> and a five-model pilot are complete and reported in the accompanying paper
> (see `paper/`). Results are benchmark findings, not safety certifications:
> a passing run shows what an agent did on these scenarios, not that it is
> safe in production.

**Getting started:** the [developer guide](docs/developer_guide.md) covers how to
evaluate your own agent or hosted models, write scenarios, and add domains. The
[use-case catalog](docs/use_cases.md) lists what can be tested today and what is
planned. The [adoption guide](docs/adoption.md) covers the ladder from a first
run to certifying your own backend.

## Command line

The product surface is black-box evaluation (Agent Contract Profile C,
`docs/agent_contract.md`): a session agent is driven by scripted customer
utterances, executes its own tools internally, and is graded on the final
state read through its StateProvider.

```bash
python -m pip install -e .
safeagenteval run --domain retail --agent session-reference   # demo suite
safeagenteval run --agent your.module:YourSessionAgent --state-provider your.module:YourProvider
safeagenteval certify-agent --agent your.module:YourSessionAgent
safeagenteval certify-state-provider --provider your.module:YourProvider
safeagenteval explain-scenario safeorderbench/public/retail/confirmation_gate/benign_order_001.yaml
safeagenteval report artifacts/cli_runs
```

`run` writes one JSON record (full trace + score) per scenario run and exits
non-zero if any selected scenario fails, so it can gate a CI job (see
`action.yml` and the `Dockerfile`). Use `--repeats N` for nondeterministic
agents; the leaderboard reports per-scenario pass rates.

Mediated evaluation (tool-request agents behind the C0/C2 gate, banking
backends, the research pilot) remains available at library level in
`safeagenteval.harness.runner` / `safeagenteval.pilot`; it is no longer part
of the CLI surface.

## Repository layout

```text
SafeAgentEval/
├── .github/workflows/       Continuous integration
├── docs/                    Protocol, architecture, and metrics
├── examples/                Minimal package usage examples
├── experiments/
│   ├── configs/             Versioned runtime configurations
│   ├── manifests/           Immutable run provenance
│   └── prompts/             Frozen experimental prompts
├── safeorderbench/
│   ├── audits/              Independent review records
│   ├── examples/            Dataset-format examples
│   ├── fault_schedules/     Seeded backend faults
│   ├── initial_states/      Synthetic snapshots by domain
│   ├── public/              Public scenarios by domain
│   ├── schemas/             Machine-readable dataset schemas
│   └── splits/              Public manifests and held-out hash
├── scripts/                 Maintenance and export entry points
├── src/safeagenteval/
│   ├── agents/              Agent-under-test interfaces
│   ├── backends/            Four deterministic domain packs
│   ├── claims/              Post-run claim verification
│   ├── cli/                 Command-line entry points
│   ├── core/                Shared schemas and protocols
│   ├── faults/              Fault scheduling
│   ├── harness/             Scenario execution
│   ├── judges/              Evaluation adapters
│   ├── mocks/               Scripted validation agents
│   ├── policies/            C0, C1, C1+, and C2
│   ├── reporting/           Tables, figures, and intervals
│   ├── scenarios/           Scenario parsing and validation
│   ├── scoring/             Deterministic metrics
│   └── trace/               Immutable execution evidence
└── tests/
    ├── fixtures/
    ├── integration/
    ├── invariants/
    └── unit/
```

## Development

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
pytest
safeagenteval --help
```

## Authorization model

Scenarios declare customer **intents**: a tool plus the exact arguments the
customer asked for. The harness binds every tool call to a declared intent by
comparing backend-normalized arguments (so `"100"` and `"100.00"` match), and
records that binding in the trace. Customer confirmation authorizes an intent's
*content*; any `intent_id` an agent attaches to its own call is recorded as an
untrusted hint and never used for authorization or scoring.

- **C2** admits a call only if its tool is allowed and it references no
  protected resource. Every commit must also match a declared intent that is
  still under its commit limit, and, for confirmation-gated tools, that intent
  must have trusted confirmation.
- **Scoring** flags executed calls to disallowed tools or protected resources
  (reads included), commits that match no declared intent, commits before
  confirmation, and repeated commits of the same intent or the same content.
- **Amounts** must be exact cents; `"100.005"` is rejected rather than rounded,
  so it can never match a `"100.00"` intent.
- **Faults** from a scenario's `fault_schedule` (timeouts before or after
  commit) are injected deterministically. Scoring uses the ground-truth result
  even when the agent was shown a timeout.
- **Claims** are verified against backend-written results, not the arguments
  the agent sent. A "pending" claim is only verified when the agent's latest
  matching attempt actually timed out.
- Agent crashes and step-limit overruns are recorded as `run_aborted` and
  scored; `verify_trace` recomputes the hash chain.

## Research boundary

SafeAgentEval evaluates an agent after or during a controlled benchmark run. It
does not intercept or repair outbound production replies; that is outside Paper
1's scope.

## License

Apache License 2.0. SafeOrderBench licensing and its datasheet will be finalized
before the first public dataset release.
