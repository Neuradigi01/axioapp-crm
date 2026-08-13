# Step 4 — Publish inbound events (WA + Email) + cross-tenant guard + SPF/DKIM

**Goal:** Publish `whatsapp.message_received` and `email.message_received` events from the inbound paths, with SPF/DKIM checks for email and a cross-tenant assertion for WhatsApp — without breaking the existing inline auto-reply / keyword-rules paths.
**Depends on:** none (independent of Steps 1-3 — this step only touches conversations + events)
**Status:** Pending

## Scope

**In-scope**
- Add `email.message_received` to `core/events/event_catalog.py`; wire description.
- Extend `conversations/service.py:receive_webhook()` to publish `whatsapp.message_received` AFTER the existing inline path runs, only when `direction='in'`.
- Extend `adapters/email.py:receive_email()` to run SPF + DKIM check, and publish `email.message_received` on pass.
- Cross-tenant assertion inside `receive_webhook`: `conversation.org_id == resolved_org_id == contact.org_id`; on mismatch, publish nothing and fire `security.cross_tenant_webhook_rejected` audit event.
- Payload shape includes `is_first_message` boolean derived from whether the conversation had prior messages (Decision §2).

**Out of scope**
- Subscribers / trigger matching — Step 5.
- SPF/DKIM library choice (use existing if `email-validator` / `dkimpy` already present; add if not).
- Handling for shared inbound aliases across orgs — documented out-of-scope in README §What NOT included.

## Files to touch

- `API/src/app/core/events/event_catalog.py` (modified — add `email.message_received`)
- `API/src/app/core/conversations/service.py` (modified — publish WA event, cross-tenant assertion)
- `API/src/app/core/conversations/adapters/email.py` (modified — SPF/DKIM + publish)
- `API/src/app/core/audit/service.py` or wherever `security.*` events are fired (called from receive_webhook)
- `API/requirements.txt` / `pyproject.toml` (modified only if `dkimpy` or equivalent needs adding)

## Plan

1. Event catalog — add `EMAIL_MESSAGE_RECEIVED = "email.message_received"` with description "Inbound email from a contact".
2. `receive_webhook()` — after all existing inline processing (auto-reply + keyword rules + assignment + AI), and after the DB `flush` that persists the inbound `Message`:
   - Assert `resolved_org_id == conversation.org_id == contact.org_id`; mismatch → audit + early return without publishing.
   - Build payload `{org_id, conversation_id, contact_id, message_id, text, is_first_message, direction: "in"}`.
   - `bus.publish("whatsapp.message_received", payload)`.
3. `receive_email()`:
   - Run SPF check (via `email-validator` or `dkimpy` — pick whichever is already in the tree; if neither, add `dkimpy`).
   - Run DKIM signature verification.
   - Fail-closed: SPF or DKIM fail → log `chatbot.email.spf_dkim_failed` + do NOT publish.
   - On pass, persist message as today, then publish `email.message_received` with the same payload shape.
4. `is_first_message` derivation — count messages on the conversation BEFORE this one; `count == 0` at time of insert → `is_first_message = true`.
5. Do NOT change the existing inline auto-reply logic — coexistence precedence lands in Step 5's matcher, not here.

## DB changes / migrations

None.

## Tests to add

Location: `API/tests/core/conversations/test_inbound_events.py`

- `test_whatsapp_webhook_publishes_message_received` (T2)
- `test_email_inbound_publishes_when_spf_dkim_pass` (T3)
- `test_email_inbound_no_publish_when_spf_fails` (T4)
- `test_email_inbound_no_publish_when_dkim_fails` (T4)
- `test_cross_tenant_webhook_rejected` (T5) — WA phone routed to org A but conversation exists in org B → no publish, `security.cross_tenant_webhook_rejected` fires.
- `test_first_message_flag_true_on_new_conversation` (T2)
- `test_first_message_flag_false_on_second_message` (T2)
- `test_existing_inline_auto_reply_still_fires` (T1 — regression).

## Verification checklist

**Backend**
- [ ] Existing inline auto-reply / keyword-rules behavior unchanged (manual: send a keyword-rule-matching inbound and see the inline reply).
- [ ] `bus.publish` calls visible in logs when inbound arrives.
- [ ] SPF/DKIM failure logs visible; no publish.
- [ ] Cross-tenant test scenario logs `security.cross_tenant_webhook_rejected` and does not publish.

**Frontend** — N/A.

**Code review**
- [ ] Publish happens AFTER all DB writes, INSIDE the same transaction? — no, publish is post-commit (or explicit `after_commit` hook if the bus is transactional). Confirm the bus semantics with existing publishers (`lead.created` etc).
- [ ] No blocking network call inside `receive_webhook` — publish is fire-and-forget (Celery-enqueue).
- [ ] Payload includes only fields explicitly listed — no accidental PII bleed (e.g. no full contact serialization).

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` in every publish payload
- [ ] Sidebar / permissions N/A
- [ ] Reuse — reused existing event bus, existing SPF/DKIM lib if present
- [ ] Query efficiency — `is_first_message` derived via `SELECT count(*)`; consider `EXISTS` or check if conversation has a `message_count` column already (reuse if so)
- [ ] Zero TODOs

## Stop & report

Report the exact bus.publish call sites (file:line), the payload shape, and confirm the existing inline behavior via a manual test transcript. Await "proceed".
