# Adoption guide: from first run to your own black-box evaluation

SafeAgentEval's product surface is black-box evaluation (Agent Contract
Profile C, `docs/agent_contract.md`): most production agents are
session-shaped (CCE-like) — one utterance in, a reply out, tools executed
internally. The harness drives them with scripted customers, seeds and reads
their world through a StateProvider, and grades the final state. Adoption is
a ladder; each level is useful on its own.

| Level | Goal | Time | Command / artifact |
|---|---|---|---|
| L0 | See it work | 5 min | `safeagenteval run --domain retail --agent session-reference` |
| L1 | Test your session agent | Hours | A `SessionAgent` adapter (`say(text)`) + a `StateProvider`, then `safeagenteval run --agent your.module:YourAgent --state-provider your.module:YourProvider` |
| L2 | Add your scenarios | Hours–days | YAML with `execution_mode: black_box` under `safeorderbench/public/<domain>/<category>/`, then `safeagenteval lint-scenario <file>` and `explain-scenario <file>` |
| L3 | Certify your adapter + provider | Days | `safeagenteval new-session-agent myshop`, then `certify-agent` (AGT-01…05) and `certify-state-provider` (SP-01…04) with reports attached |
| L4 | Grade you
...[truncated 2112 chars]