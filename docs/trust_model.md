# Trust model: who may hold the measuring instrument

SafeAgentEval grades an agent by the final state read through a
StateProvider. That makes the provider the **trust root** of every
verdict: a snapshot that lies produces a verdict that lies, and no
scoring rule downstream can detect it. This document states who must
operate the provider for a result to mean something, what the harness
checks on its own, and how results are labeled.

## The blunt rule

> **Results where the evaluatee operated the StateProvider are
> self-reported. They are labeled as such and are not certified
> evidence.**

The evaluation scenarios and their authorized final states are public.
An evaluatee who controls the agent *and* the provider can return a
published authorized state without the agent doing anything, and can
answer with canned replies. No black-box framework can prevent that
from inside the evaluatee's own environment — the same reason an
emissions test means nothing when the manufacturer owns the lab.
Trust therefore comes from **separation of the measuring instrument
from the party being measured**, verified continuously.

## Roles

| Piece | Operated by | Notes |
|---|---|---|
| Harness, scenarios, customer utterances | Evaluator | The test itself is always the evaluator's |
| Sandbox tenant and seed/read APIs | Vendor provides access | Sandbox only, synthetic customers, never production |
| StateProvider code | Vendor may draft; evaluator reviews and pins | ~3 methods; certified tier requires the evaluator to have seen the source |
| StateProvider execution and credentials | **Evaluator** | Evaluator's environment, evaluator-held read credentials against the system of record |
| LLM judges, claim extractor | Evaluator | Post-run measurement only; never the verdict |

Vendor authorship of the provider is acceptable. Vendor *control* of
its execution is not, for certified results.

## Trust tiers (recorded on every run)

Every `SavedRunRecord` carries `provider_trust`, shown in reports:

| Tier | Meaning | Evidentiary weight |
|---|---|---|
| `harness` | The evaluator operated the provider against a sandbox they control | Certified |
| `auditor` | An independent auditor operated it against the vendor's system of record | Certified |
| `self_reported` | The evaluatee ran everything themselves (the default) | Indicative only; labeled, never certified |

`--provider-trust` on `run`/`matrix` sets the label. Setting it does
not create the control — it declares it, and the declaration is part
of the permanent record.

## What the harness verifies itself (implemented)

1. **Seed read-back.** Immediately after `seed()`, the snapshot must
   equal the scenario's initial state exactly, or the run aborts
   before the agent receives an utterance. A provider that cannot
   faithfully reproduce what it was given never gets to report an
   outcome.
2. **Randomized provider probe** (`--provider-probe`). Before the
   scenario is seeded, the provider must round-trip a fresh random
   probe state (random token per run). A provider that behaves
   honestly only during published conformance checks (SP-01…SP-04 use
   a fixed, public probe) cannot predict this one.
3. **Per-turn snapshots.** State is snapshotted after every customer
   turn (`turn_state` events in the hash-linked trace). Fabrication
   must then be a consistent *timeline*, not a single invented ending,
   and claims are graded against the state in force when they were
   spoken.
4. **State invariants.** Independent of the provider, the harness
   checks banking-shaped snapshots for internal consistency: valid
   non-negative balances, positive cent-exact transfer amounts,
   unique transfer ids, transfers referencing real accounts/payees,
   and per-account balance conservation (money that left an account
   equals the transfers out of it). Violations are recorded
   (`invariant_violations`) and fail the run.
5. **Provenance hashes.** Each record carries `scenario_sha256`
   (exact scenario content graded against) and `snapshot_hash`
   (canonical final state), and the trace is hash-linked end to end.
   Publishing the run manifest with a release anchors the chain heads
   outside the runner's control.

## Defeating canned agents and public answer keys

The public scenarios are a published test: necessary for
comparability, insufficient against preparation. Certified vendor
evaluations should therefore also use **private and randomized
scenario variants** — the client generates fresh amounts, balances,
names, ids, and injection wording at evaluation time (secret seed) and
computes the authorized final states from the generated parameters.
An agent keyed to the public pack has never seen these cases and must
genuinely interpret the customer. Private scenario sets are supported
today (any root folder via `--suite`); a frozen held-out split with a
published hash commitment is planned (see `safeorderbench/splits/`).

For the highest assurance, read the final state through **two
independent channels** (e.g., the provider's ledger API and a
separately obtained sandbox statement export) and require agreement.

## Residual risk, stated plainly

An evaluatee controlling agent + backend + provider, whose results
are nonetheless presented as certified, defeats any black-box method;
the labeling above exists to make that a governance failure rather
than a silent one. Within the certified tiers, the controls here make
fabrication require an internally consistent, timeline-consistent,
probe-surviving deception under independently held credentials —
detectable on audit and, with randomized variants, pointless to
attempt.
