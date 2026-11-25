# Documentation

Research protocol, architecture, metric definitions, and contributor guidance
belong here. Documentation must distinguish implemented behavior from planned
work and reported experimental evidence.

- [Agent contract](agent_contract.md): the normative black-box interface
  (Profile C) agents and StateProviders are evaluated against.
- [Developer guide](developer_guide.md): adopting and extending the framework.
- [Trust model](trust_model.md): who must operate the StateProvider for a
  result to count, the harness's provider controls, and trust-tier labeling.
- [Enterprise customers](customers.md): who the product is for, and how a
  buyer, an internal team, an auditor, and a vendor each use it.
- [Vendor review playbook](vendor_review_playbook.md): how a client evaluates
  an agentic banking-payments vendor end to end.
- [Adoption guide](adoption.md): from a first run to comparing vendors.
- [Pack maintenance policy](pack_maintenance_policy.md): which packs are
  actively maintained, which are partner-driven or compatibility-only,
  and the bounded-maintenance commitment for the project.
- [Use-case catalog](use_cases.md): what can be tested, by failure category and status.

SafeOrderBench (banking, 16 scenarios) is the only scenario pack
shipped with the framework; its scenarios live in `safeorderbench/`
in the repository root. Other domains are expressed as packs that
their owning organizations author themselves.
