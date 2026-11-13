# CCE compliance review — against Agent Contract Profile C

Review of the CCE (Cognitive Commerce Engine) source at `apps/cce` in
the CCL repository, read as the reference implementation for the shared
policy / compliance / safety / PII pack (`docs/shared_pack.md`). CCE is
a restaurant voice/chat/phone ordering engine (STT → NLU → dialog →
UCA order API). It is **not** Profile-C compliant out of the box; this
review maps what it already enforces, what an adapter must translate,
and where the shared pack must test rather than trust.

## What CCE already enforces (verified in source)

| Control | Where | What it does |
|---|---|---|
| Per-channel turn policy as a table | `channel/turn_policy/policy.py` | CHAT / VOICE / PHONE all run the same stages (`pii_redaction`, `prompt_injection`, `sentiment`, `allergen_capture`, `hard_ood`); `validate_policies()` runs at import, so a channel that makes no statement about a stage is a startup error. Unknown channels get the full policy |
| Guards fail closed | `policy.py` `_handle_stage_failure` | A raising guard blocks the turn ("input safety check unavailable"); enrichment stages fail open |
| PII redaction first | `turn_policy/guards.py`, `utils/pii_redact.py` | Presidio redacts `EMAIL_ADDRESS`, `PHONE_NUMBER`, `CREDIT_CARD` (Luhn), `US_SSN` before injection detection, classification, the LLM, history, and the evaluation store |
| Prompt-injection guard | `guards.py`, chat `sanitize.py` | Instruction-override text is refused before classification, tools, and persistence; persisted history stores `[blocked unsafe instruction]` instead of the attack text |
| Confirmation before commit | `services/zeno_tools.py` `submit_order`, `prompts/agent/system.md` | The tool and the system prompt both require explicit placement confirmation; a bare "yes" counts only when the previous assistant turn asked to place the order |
| Independent safety veto | `services/agents/safety_agent.py` | A separate allergen reviewer runs *before* the order reaches UCA; a veto blocks submit and returns substitutes |
| Idempotency (two layers) | `channel/chat/middleware/idempotency.py`, `submit_order` cart fingerprint | `X-Client-Request-Id` dedupe (tenant-namespaced, 5-min TTL) plus a per-cart fingerprint replay at submit |
| Tenant/session binding | `channel/chat/routes.py` `_resolve_session` | A session reused with a different tenant, location, or resource is rejected (409) |
| Tool least-privilege (mostly) | `services/tools/registry.py`, `manifest.py` | Tools are namespaced (cart, menu, safety, pricing, fulfillment, lifecycle, identity, escalation, discovery) and bound per intent |
| Post-submit window | `zeno_tools_commerce.py` | Cancel / modify-after-submit only inside a 90-second window |
| Pricing integrity | `core/money`, `PricingService`, `promo_service.py` | Totals recomputed from lines in one `Money` type; promos validated against UCA, not invented |
| Privacy-minimized eval records | `services/evaluation_store.py` | Turn records are redacted, append-only, and risk-tagged (injection, allergy, checkout, escalation) for review queues |

## Findings the shared pack must test (not assume)

| # | Severity | Finding |
|---|---|---|
| F1 | **High** | **Safety veto fails open.** In `submit_order`, if the SafetyAgent raises, the exception is swallowed ("never fail submit on agent error") and the order proceeds — the opposite of the turn-policy guards, which fail closed. Test: safety check unavailable at commit time |
| F2 | **High** | **PII coverage is structured-only, English-only.** `PERSON`/`LOCATION` NER was deliberately dropped (menu false positives), and Presidio runs `en` only. Names, addresses, and non-English PII can reach the LLM, history, and cross-session memory. `set_address` necessarily handles address PII downstream |
| F3 | Medium | **Evaluation records persist raw cart snapshots.** `EvaluationStore.record_turn` redacts input/response text but stores `cart_before`/`cart_after` verbatim; a cart carrying fulfillment address or notes can persist PII the text redactor removed |
| F4 | Medium | **Cross-session memory is long-lived.** `UserMemoryService` keeps last order + allergens for 90 days keyed by `user_key` (auth id, hashed phone, or device cookie), with `reorder_last` recall. No consent, clear, or erasure path was found in review. Test own-key recall, other-key non-disclosure, and preference clearing (`clear_allergens`) |
| F5 | Medium | **Unknown intent gets every tool.** `tools_for_intent` falls back to all namespaces ("prefer recall"). Test that an unclassifiable turn cannot reach commit tools without confirmation |
| F6 | Medium | **Idempotency window is 5 minutes.** Chat dedupe expires; beyond it, only the cart fingerprint prevents a duplicate submit. A changed cart (add one item, resubmit) is a new fingerprint by design. Duplicate tests must include the post-TTL and retry-after-timeout shapes |
| F7 | Low | **Attachments are accepted but not processed** (chat warns). Any attachment text is an untested data layer — the email pack treats attachments the same way |
| F8 | Low | **Heuristic safety limits are documented in code**: no ingredient trees, no cross-contamination, no severity grading. Allergen cases must include a hidden-allergen variant the heuristic is expected to miss, recorded as a known-limit result |

## What an adapter must translate (Profile C surface)

CCE's chat API is the natural adapter target:

```text
POST /api/v1/chat/message
{message, session_id, tenant_id, location_id, language, metadata}
→ {response_text, session_id, intent, cart, cart_diff, metadata{tools_called, …}}
```

A SafeAgentEval `SessionAgent` adapter maps `say(text)` to that call:
one fresh `session_id` per run (AGT-04), `response_text` →
`SessionReply.text`, and the response `metadata` recorded as untrusted
claims. Note the framework's stock `HttpSessionAgentAdapter` posts
`{session_id, transcript, channel: "chat"}` and reads `reply` — CCE
needs the field mapping above, so CCE requires its own thin adapter,
not the stock one. Channel must be set per engagement (chat here;
email for InquiryAgent-style agents).

There is **no StateProvider for CCE today**. One must be built against
the system of record: seed/snapshot must cover the Redis session cart
*and* UCA orders (plus menu availability where a case needs it), and
reset must clear the session and any test-tenant orders. Until
SP-01…SP-04 pass against that provider, CCE results are indicative,
and — because Pendoah/CCE would operate both agent and provider —
labeled `self_reported` unless the evaluator runs the provider.

## Verdict

CCE is a strong reference for *input-side* policy (redaction, injection,
channel parity, fail-closed guards) and *commit-side* confirmation and
idempotency. Its known weak points — safety-veto fail-open (F1), PII
scope (F2/F3), memory lifetime (F4), and tool fallback breadth (F5) —
are exactly what the shared pack turns into tests. That is the design
principle of `docs/shared_pack.md`: every control above becomes a
case an agent must pass, in every domain, rather than a property one
implementation is believed to have.
