# Shared pack — banking instantiation

Executable instantiation of the domain-neutral policy gates
(`docs/shared_pack.md`, registry in `safeagenteval.shared_pack`) for
the banking domain. 30 scenarios: the 15 scenario-mode gates, each as
an adversarial case plus a benign twin. `CMP-4` (audit record
integrity) is a conformance gate and has no scenario by design.

Layout mirrors SafeOrderBench so the existing loader and CLI work
unchanged:

```text
sharedpack/
├── initial_states/banking/   Seeded account states
└── public/banking/           Scenarios by framework category
```

Run it:

```bash
safeagenteval run --suite sharedpack --domain banking --agent session-reference
```
