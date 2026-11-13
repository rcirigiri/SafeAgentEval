# Enterprise customers

The end customer is an institution that will let an agent commit a change
on a system of record, and that has to decide whether the agent may do
so. The grade is the sandbox ledger after the conversation. A team that
only needs to know which model chats more fluently is outside this
product.

The released exam is the banking pack in SafeOrderBench (16 scenarios,
seven categories). Pharmacy, retail, travel, and crypto or stablecoin
payments are roadmap domains. They are not current customers of a
released pack. Each new domain is claimed only when it has its own
realistic state provider, paired adversarial and benign scenarios, and
external review. See the [adoption guide](adoption.md) for the ladder
from a first run to a vendor comparison, and the
[vendor review playbook](vendor_review_playbook.md) for the procurement
exam in full.

## Who uses it

The people who use SafeAgentEval inside the institution are the ones who
own the decision, the sandbox, or the evidence.

| Customer | The decision they own | How they use SafeAgentEval |
|---|---|---|
| Bank, payments fintech, or platform buying an agent | Which vendor may move customer money, and on what limits | The same 16 scenarios against every vendor's sandbox. Compare pass rates by category and by repeat, then accept, limit, or reject |
| The same firm building its own agent | Whether a model, prompt, or tool change may ship | `safeagenteval run` in CI. A non-zero exit, or a pass rate under the agreed floor, blocks the release |
| Independent auditor | Whether a result counts as certified evidence | Operates the StateProvider with auditor-held credentials against the vendor's sandbox. The record is labeled `auditor` |
| Agent vendor | Whether they can be evaluated, and whether a later change stays inside the buyer's bar | Supplies a session endpoint and a synthetic sandbox. May draft the StateProvider. The buyer reviews it, pins it, and runs it. After acceptance, the vendor runs the pack on every change |

A result where the party being measured also operated the StateProvider
is labeled `self_reported` and is not the basis for a buy decision. See
[trust model](trust_model.md).

## How a buyer runs an evaluation

This is the procurement exam. The playbook is the normative procedure;
the steps below are the customer-facing shape of it.

1. **Risk sets the rules first.** Scope is the banking pack and its seven
   categories. Thresholds are written down before anyone sees a score:
   for example, every adversarial scenario must pass, with zero tolerance
   for an executed injection, a privacy disclosure, or a duplicate
   payment. Repeats are 5–10, because the agent is nondeterministic. The
   trust tier is `auditor` or `harness`.
2. **The vendor opens a sandbox, never production.** Synthetic customers
   only. One utterance in, one reply out. A fresh session per scenario.
   The buyer gets read access to the system of record.
3. **Two gates.** `certify-agent` and `certify-state-provider` must pass
   before any score is believed. A failed gate is itself a finding: the
   integration cannot be measured.
4. **Business owners check the answer key.** They run `explain-scenario`
   on one benign case and one adversarial case and confirm the allowed
   ending matches policy. Sending an extra payment on a confirmed
   instruction is an ending that must not occur.
5. **The full pack runs.** Ten repeats, a provider probe, and a private
   or randomized suite so the vendor cannot have prepared only for the
   published files. Each run is kept as a hash-linked record.
6. **Results are read in three cuts, never as one average.** Adversarial
   versus benign, so an agent that refuses every payment fails the
   legitimate transfer. By category, so a vendor can look fine overall
   and fail every duplicate-payment case. By repeat, so 7 of 10 is an
   incident rate.
7. **People review the evidence, then decide.** Reviewers inspect every
   adversarial failure and a sample of passes. The vendor receives the
   failing traces. Both sides argue from the same hash-linked record.
   The outcome is accept, conditional (amount caps, human approval above
   a limit, a scheduled retest), or reject. After a fix, the failed
   categories and the full pack are rerun, because a fix often breaks
   the benign twin.

The playbook's own effort estimate is about half a day to set
thresholds, two to three days to review the answer key, and three to
five days to review failures. Elapsed time is typically three to five
weeks. Most of that is the vendor preparing the sandbox.

After acceptance, the pack stays in the vendor's CI on every model,
prompt, or tool change. The buyer re-runs quarterly and on major
updates, rotating in new private variants.

## How a firm uses it on its own agent

The same contract, without a vendor. Engineering adds a `say(text)`
adapter and a StateProvider that seeds and reads the firm's test ledger.
Risk reviews the scenarios, including private ones transcribed from the
firm's own incidents. CI runs the pack on each change. A crash, an extra
transfer, or a contradicted "done" is a failed run with a trace.

Company-specific cases stay in a private folder and are passed with
`--suite`. The public banking pack is the shared floor. The private
suite is how the firm encodes its own mandates, payees, and past
incidents. A passing run shows what the agent did on these scenarios
under whoever held the StateProvider. It is not a safety certificate
and not a regulatory approval.
