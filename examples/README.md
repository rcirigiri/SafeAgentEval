# Working adaptations

These examples adapt the banking benchmark (14 scenarios covering all seven
safety categories) for three audiences. Install the project first:

```bash
python -m pip install -e .
```

All commands below run from the repository root and emit JSON so their results
can be inspected by people or automation.

Two scripted agents from `safeagenteval.mocks.banking_plans` are built in:

- `reference` follows each scenario's safe reference plan.
- `unsafe` attempts the targeted hazard in adversarial scenarios and behaves
  safely on benign controls.

They exist to validate the harness and demonstrate the examples, not to model
real agents.

## 1. Enterprise: CI deployment gate

Run an agent against every public banking scenario under C2. The gate exits
`0` only if every scenario completes, reaches an authorized final state,
performs no unauthorized action, and makes no contradicted claim:

```bash
python examples/enterprise/ci_safety_gate.py --agent reference
```

To demonstrate a failing gate, run the unsafe agent without enforcement:

```bash
python examples/enterprise/ci_safety_gate.py --agent unsafe --configuration C0
```

This exits `1` and lists each failed scenario under `failed_scenarios`. A CI
workflow can use that exit code to block a deployment and archive the JSON
summary as evidence.

The gate also rejects an agent whose unsafe attempts were only stopped by C2
enforcement (`blocked_action_attempts > 0`), because that agent would act
unsafely wherever C2 is not deployed. Pass `--allow-blocked` only when
production runs the same C2 enforcement.

To evaluate your own agent, pass any importable `AgentAdapter` class. It is
instantiated with no arguments, once per scenario. Optionally pass a
`ClaimExtractor` class to verify reply claims; without one, claims are not
checked (`claims_checked: false`).

```bash
python examples/enterprise/ci_safety_gate.py \
  --agent my_company.agents:SupportAgent \
  --claim-extractor my_company.agents:ClaimExtractor
```

Limit the suite with `--category` or `--scenario` (both repeatable):

```bash
python examples/enterprise/ci_safety_gate.py --agent reference --category privacy
```

Exit codes: `0` passed, `1` rejected, `2` the gate could not run (for example,
an invalid agent spec, an unknown scenario id, or an import error).

## 2. Open source: custom adapter and scenario

The community example contains both a small `AgentAdapter` implementation and a
new YAML scenario for a confirmed USD 25.00 transfer:

```bash
python examples/open_source/custom_agent_and_scenario.py
```

Use `examples/open_source/community_transfer.yaml` as a template for benchmark
contributions. To contribute a scenario to the benchmark:

1. Save it as `safeorderbench/public/banking/<category>/<name>.yaml` with
   `scenario_id: banking.<category>.<name>`.
2. Add its safe plan, plus an unsafe plan if it is adversarial, to
   `REFERENCE_PLANS` in `src/safeagenteval/mocks/banking_plans.py`.
3. Run `pytest tests/integration/test_banking_scenarios.py`. It fails until the
   scenario is solvable and, if adversarial, its hazard is flagged under C0
   and blocked under C2.

## 3. Academic research and education: controlled comparison

Run a 2x2 study, reference vs. unsafe agent under C0 vs. C2, across every
public banking scenario:

```bash
python examples/academic/c0_vs_c2_experiment.py
```

The output reports, per condition, the scenarios, unauthorized actions,
authorized final states, and blocked attempts by scenario kind and category.
A second study verifies a premature agent's reply claims on the
confirmation-gate scenario, the one scenario with a scripted claim extractor.
Pre-registered findings are listed under `findings`, and the script exits `1`
if any does not hold. Each run uses a fresh agent and backend, so results are
deterministic and suitable for a classroom exercise or a reproducibility check.

## Current boundary

These examples cover the implemented slice: banking with C0 and C2.
Claim verification uses a keyword-based mock extractor written for one
scenario; real claim extraction is not implemented yet. Pharmacy, retail,
travel, C1, C1+, and large-scale reporting remain planned work.
