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
- [Use-case catalog](use_cases.md): what can be tested, by failure category and status.
- [SafeCartBench pack spec](safecartbench_pack.md): the proposed
  order-support pack (Shopify orders, refunds, status) — 7 scenario
  families as a pilot, and what a production gate requires.
- [SafeGateBench (shared pack)](shared_pack.md): the domain-neutral policy gates —
  policy, compliance, safety, and PII; 16 parameterized gates applied
  to every agent, on top of its domain pack.
