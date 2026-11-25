# Pack maintenance policy

AgentSafetyRecord is a framework with scenario packs. The framework and
one flagship pack (SafeOrderBench, banking) are maintained products;
the remaining packs are supporting pilots and partner-driven
templates. This policy states, per pack, what
maintenance a user or design partner can expect, so that pilot packs
are never mistaken for abandoned ones and the flagship pack is never
diluted by breadth.

## Maintenance levels

- **Actively maintained** — new scenarios, documentation, and
  framework-driven improvements are initiated by the maintainer.
- **Compatibility-only** — no new content is initiated. The pack is
  kept green against framework changes: when the harness, models, or
  loader change, the pack's discrimination tests are run and minimal
  fixes are made so the pack continues to pass. Expected effort in a
  normal month is near zero.
- **Partner-driven** — a compatibility-only pack that advances when
  its design partner moves: partner state-machine corrections,
  answer-key validation, scenario review, or sandbox access. Between
  partner inputs the pack is frozen by design, not by neglect.
- **Framework component** — not a domain pack. Maintained once,
  centrally, as part of the framework, and inherited by every pack.

## Per-pack status

| Pack | Level | Notes |
|---|---|---|
| SafeOrderBench (banking) | Actively maintained | Released flagship; reference implementation for pack authors |
| SafePayBench (payments) | Partner-driven | Supporting pilot; two-ledger settlement/issuance domain; advances on design-partner validation |
| SafeCartBench (commerce) | Partner-driven | Spec-first; advances on design-partner validation of the order/refund state machine and answer keys |
| SafeTradeBench (trading) | Partner-driven | Advances on design-partner review, dry runs, and sandbox endpoints |
| SafeBookBench (booking) | Compatibility-only | Pilot implemented; advances if the booking design partner re-engages |
| SafeCareBench (healthcare admin) | Compatibility-only | Pilot implemented, synthetic data only; advances on committed healthcare-partner validation of PHI boundaries |
| SafeGateBench (16 gates) | Framework component | Cross-domain conformance gates (policy, compliance, safety, PII), bound by each pack; not a domain |

## Rules

1. No new domain pack is started without a named design partner who
   has committed to validate that domain's state machine and scenario
   answer keys. Spec-only breadth is not a goal.
2. A partner-driven or compatibility-only pack receives new scenarios
   only in response to partner or user input — issues, corrections,
   contributed scenarios, or adapters — never to keep a catalog
   uniformly busy.
3. Pack status changes are made by editing this file and the README
   catalog together, so the public record always matches this policy.
4. Verdict integrity is not delegable: scenario and answer-key
   approval, trust-tier labeling, and release decisions remain with
   the maintainer regardless of who contributes a scenario.

## Bounded-maintenance commitment

Maintenance is intentionally bounded so the project can be sustained
by a single maintainer alongside other professional obligations:

- All work is public, open-source (Apache-2.0), and performed on the
  maintainer's own time and equipment; the project uses no employer
  resources, data, customers, or confidential information.
- Routine upkeep is limited to keeping the test suite green and
  reviewing external contributions; new development is episodic and
  partner- or release-driven, not a standing operational obligation.
- If the maintainer's availability changes — including at an
  employer's request — the project can be frozen at any time without
  stranding users: the code and scenario packs are Apache-2.0, the
  released packs remain usable as-is, and anyone may fork and
  continue them. Freezing requires no one's permission and breaks no
  commitment, because no service, SLA, or customer deployment is
  offered.
