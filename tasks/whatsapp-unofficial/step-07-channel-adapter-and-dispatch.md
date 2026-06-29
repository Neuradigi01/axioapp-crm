# Step 7 — WhatsApp Web channel adapter + conversations dispatch shim

**Goal:** Wire the outbound path so the existing Conversations send pipeline works on Web sessions. Add one `WhatsAppWebAdapter` that implements the `ChannelAdapter` Protocol and calls the sidecar via the Step-5 client. Add a ~10-line dispatch shim in `core/conversations/service.py` so when channel=whatsapp, the org's active `Integration.provider` decides which adapter (cloud vs web). Everything downstream of the adapter — composer, inbox, automation, opt-in checks, block list, internal notes, tags — works unchanged.
**Track:** WhatsApp Unofficial (Baileys)
**Status:** Pending
**Depends on:** Step 6 (events receiver — inbound already lands in `tbl_messages`).

---

## Scope

In-scope:

- **`core/conversations/adapters/whatsapp_web.py`** — new `WhatsAppWebAdapter` class implementing `ChannelAdapter`:
  - `__init__(*, session_id: str, sidecar_client: SidecarClient)` — `session_id` is the sidecar session id (the same UUID stored on `WhatsAppWebSession.sidecar_session_id`).
  - `send(*, org_id, external_id, text, attachments, interactive=None, reply_to_channel_message_id=None) -> ChannelMessageRef`:
    - **Refuse `interactive`** — Baileys doesn't support Meta interactive types. Raise `UnsupportedOperation("interactive messages not supported on WhatsApp Web")`. Service layer maps to 400 with the message.
    - Normalise `external_id` to digits-only (existing `_normalize_phone` helper from `adapters/whatsapp.py` — import + reuse, don't duplicate).
    - **Location attachment** — extract from `attachments` (same shape as Cloud adapter consumes). If present: call `sidecar_client.send_location` (Step 7 extension below).
    - **Media attachment** — extract from `attachments`. Sidecar's `/send-media` expects `base64`; the CRM stores media under `./storage/`. Read file → base64 → POST. Helper: `_load_media_base64(media_id: str) -> tuple[str, str]` returning `(base64_data, mime_type)`.
    - **Text fallback** — call `sidecar_client.send_text(session_id, to, text, reply_to=...)`.
    - On success: return `ChannelMessageRef(channel_message_id=result['message_id'], sent_at=now())`.
    - On `SidecarRateLimited` → raise the existing `WhatsAppRateLimited` exception (reuses the Cloud retry-after handling).
    - On `SessionNotConnected` → raise a new `WhatsAppWebNotConnected` exception (mirrors `WhatsAppNotConnected` semantics — service maps to 409).
  - `send_reaction(*, external_id, target_channel_message_id, emoji)` — Baileys supports reactions natively. Calls `sidecar_client.send_reaction(session_id, to=external_id, target_id=target_channel_message_id, emoji=emoji or "")`. The sidecar's `messages.ts` route needs the matching endpoint (small extension to Step 3 — call it out below).
  - `send_template(...)` — raise `UnsupportedOperation("templates not supported on WhatsApp Web — use Cloud API")`. Campaigns + auto-reply templates already check provider before calling; this is a defense-in-depth.
  - `parse_webhook(...)` — also raises `UnsupportedOperation`. Web doesn't have webhooks (events come through `/whatsapp-web/events` and reuse the Cloud-equivalent payload shape via Step 6's translator).
- **Sidecar extension** (small follow-up on Step 3):
  - New endpoint `POST /sessions/{sessionId}/send-reaction` `{to, target_id, emoji}` → calls `sock.sendMessage(jid, { react: { text: emoji, key: { id: target_id, remoteJid: jid, fromMe: false } } })`. Returns `{message_id, timestamp}`.
  - New endpoint `POST /sessions/{sessionId}/send-location` `{to, latitude, longitude, name?, address?}` → calls `sock.sendMessage(jid, { location: {...} })`.
  - **These two are tiny additions to the Step-3 messages.ts router**. ~30 lines TS + 2 tests.
- **`sidecar_client.py` extensions** — mirror the new endpoints (`send_reaction`, `send_location`). ~20 lines.
- **`registry.py`** wiring — register `WhatsAppWebAdapter` on the `ConversationChannel.whatsapp` channel via a factory that picks the active session at call time. This is the heart of the dispatch shim.
- **Dispatch shim — replace the existing `whatsapp` adapter factory in `core/conversations/registry.py` boot wiring:**
  - Today: there's a single factory for `whatsapp` returning a `WhatsAppAdapter` instance built from `resolve_whatsapp_adapter(...)`.
  - After: a single factory that **reads the active `Integration.provider`** for the org and returns either:
    - `WhatsAppAdapter` (provider=`whatsapp`) — Cloud
    - `WhatsAppWebAdapter` (provider=`whatsapp_web`) — Web
  - Implementation: new `resolve_whatsapp_provider_adapter(db, *, phone_id=None)` in `core/conversations/adapters/__init__.py` (or `adapters/dispatch.py` if cleaner) — async function that:
    1. Reads `Integration` rows for active org, both providers.
    2. Picks the one with `status=connected`. If both connected, picks by an explicit input arg `prefer_provider` (defaults to `whatsapp` — Cloud is the canonical choice).
    3. Returns the matching adapter.
  - The registry factory wraps this in a sync-ish shim (since `register_channel`'s factory is a zero-arg callable). Approach: **lazy resolution at `send` time** — the factory returns a small `DispatchAdapter` object that, on `.send()`, performs the lookup and delegates. Same for `parse_webhook` (Cloud).
- **`core/conversations/service.py` modification** — the existing `send_outbound` function already resolves an adapter via the registry. Two ~5-line additions:
  1. **Multi-number resolution** — existing code picks a `phone_id` from the conversation's `received_via_phone_id` or campaign's `send_from_phone_id`. For Web, the equivalent is `sidecar_session_id`. Add a parallel resolution that calls into the new `resolve_whatsapp_provider_adapter(prefer_provider=...)` when the active Integration is Web.
  2. **Unsupported-operation handling** — catch `UnsupportedOperation` and translate to 400 with a helpful "Use Cloud API for this feature" hint.
- **Audit + status events**:
  - `integrations.whatsapp_web.outbound_sent` — every successful send.
  - `integrations.whatsapp_web.outbound_failed` — every adapter failure (sidecar 502 / rate-limited / not connected).
- **Tests**:
  - `test_whatsapp_web_adapter.py`:
    - Text send happy path → calls sidecar_client.send_text + returns ref.
    - Media attachment → loads file → base64 → calls send_media.
    - Location attachment → calls send_location.
    - Interactive raises UnsupportedOperation.
    - Template raises UnsupportedOperation.
    - Sidecar 429 raises WhatsAppRateLimited with retry_after.
    - Sidecar `session_not_connected` raises WhatsAppWebNotConnected.
  - `test_dispatch.py`:
    - `resolve_whatsapp_provider_adapter` picks Cloud when only Cloud connected.
    - Picks Web when only Web connected.
    - Picks Cloud by default when both connected.
    - Respects `prefer_provider='whatsapp_web'`.
    - Returns None when neither connected.
  - `test_send_via_web_e2e.py` — mocks sidecar via respx; calls the public conversations send endpoint; asserts a `tbl_messages` row is inserted with `payload.provider='whatsapp_web'`.

Out of scope:

- **Frontend** — Step 8.
- **Multi-Web-number per org** — `WhatsAppWebSession.integration_id` is UNIQUE today. Multi-number is a separate track once the v1 single-number flow stabilises.
- **Allowing Web for campaigns** — explicitly blocked. The campaigns service already calls `resolve_whatsapp_adapter` (Cloud-specific). To prevent accidental Web sends, the dispatch shim's `prefer_provider` defaults to `whatsapp`, AND `core/campaigns/service.py` gets a 1-line guard: if the resolved adapter is `WhatsAppWebAdapter`, raise `CampaignsCloudOnly("Campaigns require WhatsApp Cloud API. Connect Cloud in Settings → Integrations.")`. ~5 lines total.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/conversations/adapters/whatsapp_web.py` | **NEW** |
| `API/src/app/core/conversations/adapters/__init__.py` | **MODIFY** — add `UnsupportedOperation`, `resolve_whatsapp_provider_adapter` |
| `API/src/app/core/conversations/registry.py` | **MODIFY** — register web; introduce dispatch wrapper |
| `API/src/app/core/conversations/service.py` | **MODIFY** — ~10 lines for shim + error handling |
| `API/src/app/core/integrations/whatsapp_web/sidecar_client.py` | **MODIFY** — add `send_reaction`, `send_location` |
| `API/src/app/core/integrations/whatsapp_web/exceptions.py` | **MODIFY** — add `WhatsAppWebNotConnected` |
| `API/src/app/core/campaigns/service.py` | **MODIFY** — 5-line Web-block guard |
| `sidecars/whatsapp-web/src/routes/messages.ts` | **MODIFY** — add `/send-reaction`, `/send-location` |
| `sidecars/whatsapp-web/tests/messages.test.ts` | **MODIFY** — extend with 2 cases |
| `API/tests/conversations/adapters/test_whatsapp_web_adapter.py` | **NEW** |
| `API/tests/conversations/test_dispatch.py` | **NEW** |
| `API/tests/conversations/test_send_via_web_e2e.py` | **NEW** |

**12 files. ~400 lines net.** Within rule-8 budget.

## Plan

1. **Sidecar additions first** — add `/send-reaction` + `/send-location` in `routes/messages.ts`. Two tests. Confirm with curl.
2. **`sidecar_client.py` extensions** — mirror the two endpoints. Two test cases in `test_sidecar_client.py`.
3. **`adapters/__init__.py`** — add `UnsupportedOperation` exception (the Protocol contract is unchanged; this is a runtime signal for adapters that can't satisfy a method).
4. **`adapters/whatsapp_web.py`** — implement `WhatsAppWebAdapter`. Reuse `_normalize_phone` from `adapters/whatsapp.py` (import, don't redefine).
5. **`resolve_whatsapp_provider_adapter`** in `adapters/__init__.py` (or split into `adapters/dispatch.py` if it grows beyond ~30 lines).
6. **`registry.py`** — refactor `whatsapp` factory to use the dispatch resolver. The `register_channel` shape is preserved (zero-arg factory) — the factory returns a tiny `LazyAdapter` that does the lookup on first `.send` call per request.
7. **`conversations/service.py`** — add the catch for `UnsupportedOperation`.
8. **`campaigns/service.py`** — single-line guard against `WhatsAppWebAdapter`.
9. **Tests** — both adapter-level and end-to-end (the e2e test posts to the real conversations endpoint with a Web-connected org; mocks the sidecar via respx).

## DB changes / migrations

**None.** No schema changes; everything is code-level.

## Tests

- 7 adapter test cases.
- 5 dispatch test cases.
- 3 end-to-end test cases.
- Sidecar tests +2.
- Total: 17 new cases.

## Smoke

```
1. Setup: org has WhatsApp Web connected (Steps 5-6 already verified
   pairing).
2. Open the existing Conversations inbox UI. The inbound conversation
   from your earlier smoke message should be there.
3. Type a reply in the composer and click Send.
4. Backend log shows:
   - core.conversations.service.send_outbound: resolved adapter=WhatsAppWebAdapter
   - sidecar_client.send_text -> 200
   - audit: integrations.whatsapp_web.outbound_sent
5. Your phone receives the reply within 1-2s.
6. Try sending an interactive message via the existing composer's
   button-builder (Step 6 of the upgrade track):
   -> 400 {"detail": "interactive messages not supported on WhatsApp Web.
            Use Cloud API."}
7. Try sending a media file:
   -> 200, phone receives the image.
8. Disconnect Web (POST /disconnect). Connect Cloud API on the same org.
9. Send another reply. Backend log shows adapter=WhatsAppAdapter (cloud).
10. Negative: with neither provider connected, send a reply:
    -> 409 with the existing "Connect WhatsApp in Settings"
       message — same UX as today, no regression.
11. Try to create a campaign while Web is connected (Cloud is not):
    -> 400 {"detail": "Campaigns require WhatsApp Cloud API. ..."}
12. End-to-end react: from your phone, react with 👍 to a message. The
    inbox shows the reaction. From the inbox, react with ❤️ — your phone
    sees the reaction within 1-2s.
```

## Risks

- **Adapter Protocol assumptions.** The existing `ChannelAdapter` Protocol expects `send` to be async + return `ChannelMessageRef`. Our Web adapter matches that exactly. **No Protocol changes.**
- **Dispatch resolution is per-request.** Each send call resolves the adapter from DB. Performance: one extra SELECT per send. Acceptable (cached at the request level since `Integration` and `WhatsAppWebSession` are already loaded by the upstream send handler in most paths). If hot-path measurement shows it, we add a per-request memo — deferred.
- **Both providers connected.** When an org has both Cloud and Web active, Cloud wins by default. Operators wanting Web specifically must pass an explicit hint (future UI affordance — Send-From picker, mirroring multi-number from Step 27a). For now: documented default, no UI surface for the override.
- **Campaigns send-guard.** The single-line guard prevents Web-only orgs from running campaigns. Without it, a campaign that resolved Web would silently send unthrottled messages → ban risk. Test the guard explicitly.
- **Auto-reply on inbound Web message.** Existing engine fires auto-reply via the channel registry. When the channel is `whatsapp` and the provider is Web, the auto-reply free-text path works; the **template fallback path** (out-of-session) fails because Web has no templates. Add a 5-line skip: if the resolved adapter is `WhatsAppWebAdapter`, the auto-reply engine never enters the template branch — falls back to free-text only. Test row.
- **Internal notes / tags / opt-in / block list.** All four are channel-agnostic at the service layer. No changes needed. Add an end-to-end test that posts a note on a Web conversation and asserts it persists with `is_internal=true` and never reaches the sidecar (auditable via the absence of a sidecar HTTP call).

## Self-check (10 rules)

- [ ] Rule 1: No core ↔ packs imports.
- [ ] Rule 2: No schema changes — existing tables and RLS rule respected.
- [ ] Rule 3–7: N/A (no new fields, no new forms, no new sidebar / permissions / pack).
- [ ] Rule 8: 12 files, ~400 lines.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. `prefer_provider` defaults are explicit. Campaigns guard is real, not a stub. Auto-reply template skip is real.

## Stop & report

```
Step 7 — WhatsApp Web channel adapter + conversations dispatch shim

Files changed:
- 3 new module files (adapters/whatsapp_web.py + 2 tests)
- 1 new e2e test
- 6 modified: adapters/__init__.py (dispatch), registry.py (factory),
  conversations/service.py (~10 lines), campaigns/service.py (5-line
  guard), sidecar_client.py (2 methods), exceptions.py (1 class)
- 2 sidecar modifications: routes/messages.ts, tests/messages.test.ts

What you can verify:
- Sending a reply from the CRM inbox to a Web-paired contact succeeds
  end-to-end (browser → FastAPI → sidecar → WhatsApp → phone)
- Cloud vs Web is picked correctly when either or both are connected
- Interactive / template sends are refused with a clear 400 on Web
- Campaigns refuse to enqueue on a Web-only org
- Auto-reply template fallback skips on Web; free-text auto-reply works
- React from inbox + react from phone both propagate correctly
- All existing Cloud send paths still pass their tests (no regression)
- pytest -k whatsapp_web: ~43 cases green

Tests added: 17 new cases across 3 new test files + 2 sidecar cases.

Self-check: 10 rules, all green.

Next: Step 8 — Frontend connect card + QR pairing modal (SSE-driven) +
end-to-end smoke checklist for ship.

Awaiting your "proceed".
```
