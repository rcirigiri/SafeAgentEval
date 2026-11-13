# Adoption guide: from first run to your own black-box evaluation

SafeAgentEval's product surface is black-box evaluation (Agent Contract
Profile C, `docs/agent_contract.md`): most production agents are
session-shaped — one utterance in, a reply out, tools executed
internally. The harness drives them with scripted customers, seeds and reads
their world through a StateProvider, and grades the final state. Adoption is
a ladder; each level is useful on its own.

| Level | Goal | Time | Command / artifact |
|---|---|---|---|
| L0 | See it work | 5 min | `safeagenteval run --domain banking --agent session-reference` |
| L1 | Test your session agent | Hours | A `SessionAgent` adapter (`say(text)`) + a `StateProvider`, then `safeagenteval run --agent your.module:YourAgent --state-provider your.module:YourProvider` |
| L2 | Add your scenarios | Hours–days | Scenario YAML under `safeorderbench/public/<domain>/<category>/`, then `safeagenteval lint-scenario <file>` and `explain-scenario <file>` |
| L3 | Certify your adapter + provider | Days | `safeagenteval new-session-agent myshop`, then `certify-agent` (AGT-01…05) and `certify-state-provider` (SP-01…04) with reports attached |
| L4 | Grade in CI / compare vendors | Days | `safeagenteval run ... --repeats N` in CI (non-zero exit on failure), or the same suite run against every vendor's sandbox; compare per-scenario pass rates from the JSON run records |

## Why adopt this for multi-vendor evaluation

In one sentence: **to choose between vendor agents fairly, before one of
them is allowed to touch real customers' money, orders, or records.**
Who those buyers are, and how each of them runs the exam, is
`docs/customers.md`.

- **Vendors will not open their systems.** You cannot inspect their code,
  prompts, or internal tools. This exam does not need that. It only talks
  to the agent and checks the result.
- **Same test for everyone.** Every vendor gets the same fake customer, the
  same starting account or cart, and the same task. No vendor can
  cherry-pick its own demo.
- **It checks what happened, not what the agent said.** An agent can reply
  "Done!" politely while sending money to the wrong person. The grade is
  the final state of the world, not the reply.
- **It catches both kinds of failure.** Each dangerous case ("do not send
  this") has a normal twin ("do send this"). An agent that refuses
  everything looks safe on the first and fails the second.
- **You keep a record.** Pass/fail run records are the evidence a buyer can
  show a team, a manager, or an auditor when defending why Vendor A was
  chosen over Vendor B.

If you only care which model chats most fluently, you do not need this.
If the agent can move money or change records, you do.

## How the state and environment are set up

No vendor is ever tested in production. Each vendor is tested in a **fake
sandbox world that can be set up, read back, and wiped clean**. One run is
six steps:

1. **Reset.** Wipe the sandbox clean (`reset()`).
2. **Seed.** Load the scenario's starting state (`seed(state)`): for
   example, a customer with $2,000 in checking, a payee named Alice, and
   another customer's account that must never be touched.
3. **Talk.** The framework plays the customer and sends the scripted
   messages one at a time through the agent's normal front door
   (`say(text)`).
4. **The vendor acts alone.** Inside its own system the agent replies and
   uses its own tools. The framework does not see or control those tools.
5. **Snapshot.** After the last message, the framework reads the sandbox
   back (`snapshot()`): balances, transfers, orders.
6. **Grade and repeat.** The final snapshot is compared with the authorized
   final state written down before the run. Then reset, and run the next
   vendor on the identical setup. Nondeterministic agents are run several
   times (`--repeats`) and reported as pass rates.

Two rules keep this honest. First, **one fresh agent session per run**:
nothing may leak from one scenario or one vendor into the next (checked by
AGT-04). Second, the snapshot must come from the vendor's **real sandbox
system of record** — the database or service API that actually holds the
test accounts — never from the agent describing what it did. The
StateProvider is the trust root of every black-box verdict, which is why
it is certified (SP-01…SP-04) before any score is believed.

> **Warning — who holds the provider decides what a score means.** The
> scenarios and their authorized final states are public. If the vendor
> being evaluated also operates the StateProvider and runs the evaluation
> itself, it can return a published authorized state without its agent
> doing anything, and no score produced that way is evidence. For a
> vendor selection, the evaluator (you, or an auditor) must run the
> provider — vendor-drafted code is fine, but reviewed, pinned, executed
> from your environment with your credentials — and results must be
> labeled accordingly (`provider_trust`: `harness` / `auditor` /
> `self_reported`). The harness helps: it aborts a run whose post-seed
> snapshot does not match the seeded state, snapshots after every turn,
> checks balance conservation and other state invariants itself, and
> with `--provider-probe` requires the provider to round-trip a random
> probe state it cannot predict. Full model: `docs/trust_model.md`;
> step-by-step vendor review: `docs/vendor_review_playbook.md`.

In this mode the framework detects and proves; it does not reach inside
the vendor's system and block a bad action mid-flight. Results are always
labeled `execution_mode: black_box`.

## Your datastore schema will differ — that is expected

Every vendor stores data differently. That adds **one extra step**, and it
does **not** require changing your database, your agent, or your tools.

The StateProvider is a **translator** that sits between the two formats:

```text
Scenario state (our format) -> translator -> your sandbox (your format)
Final grade                <- translator <- your sandbox state
```

The scenario says `ledger_balance = "2000.00"`, `payee-alice`. Your system
may store `balance_cents = 200000`, `payee_id = 8841`, `status = ACTIVE`.
The translator converts on the way in (`seed`) and converts back on the
way out (`snapshot()`), keeping a small ID map (our `payee-alice` = your
`8841`) and stripping fields the exam does not use. The grader only ever
sees the scenario format. The translator runs on *your* side: your schema
is never exposed.

| Your situation | Effort | What the work is |
|---|---|---|
| Same data, different names or formats (dollars vs. cents, `ACTIVE` vs. `active`) | Easy — hours | Rename and reformat fields inside `seed` / `snapshot` |
| Different structure (transfers stored as ledger entries, system-generated IDs, extra internal fields) | Medium — 1–3 days | Translator reshapes the data, keeps the ID map, returns only the canonical view |
| Sandbox missing a capability (cannot reset, cannot create a test customer, cannot read transfers back) | Hard — blocker | Not a translation problem. The sandbox needs that feature first; this would block any serious testing |

Three things keep the cost down:

- **Write it once.** The same translator serves every scenario, every
  repeat, and every future exam update.
- **Self-check in minutes.** `certify-state-provider` verifies
  seed/read-back round-trips (SP-01), that snapshots are isolated copies
  (SP-02), that reset actually wipes (SP-03), and that re-seeding is
  deterministic (SP-04).
- **Seed through your sandbox APIs** (admin/test endpoints or fixtures)
  rather than writing to the database directly, so the sandbox behaves
  exactly as it does for your own tests.

The genuinely hard cases are semantic, not syntactic: your `balance` means
available funds while the exam means ledger balance, or your `completed`
means submitted while the exam means settled. Field names will not catch
that; a short mapping note, reviewed against two or three worked examples,
will. Write the mapping down — it is part of the evidence.

## Vendor checklist: seamless validation

A vendor is ready to be graded when all six are true:

1. A sandbox (never production) with synthetic customers only, plus
   credentials the evaluator may use.
2. A session adapter: one customer message in, one reply out (`say(text)`,
   or the HTTP shape `{session_id, transcript}` → `reply`). Fresh sessions
   share no memory.
3. A StateProvider with `seed` / `snapshot` / `reset` against that
   sandbox, including the schema translation described above.
4. The snapshot reads the sandbox system of record and contains everything
   the grade needs (balances, transfers/orders, statuses) — not a summary
   produced by the agent.
5. Both conformance reports pass and are attached: `certify-agent`
   (AGT-01…05) and `certify-state-provider` (SP-01…SP-04).
6. A one-page mapping note: how scenario fields (amounts, IDs, statuses)
   translate to sandbox fields, with any semantic differences stated
   plainly.

Deliverable from the vendor: the adapter, the provider (with source
visible to the evaluator, so it can be reviewed and pinned), sandbox
access, the two conformance reports, and the mapping note. Nothing
else is required — no agent source code, no prompts, no internal
tool list. Note the division of control: for certified results the
evaluator executes the provider with evaluator-held credentials (see
the warning above); a vendor-run evaluation is self-reported.

## Honest limits

- A passing run shows what the agent did on these scenarios. It is not a
  safety certification and not a regulatory approval.
- A vendor that exposes no seedable, readable sandbox state cannot be
  state-graded by anyone; only its words can be judged.
- The public black-box library is small today (the banking/payments pack).
  A real selection means writing your own paired scenarios (L2) on this
  same contract.
