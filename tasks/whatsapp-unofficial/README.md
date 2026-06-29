# WhatsApp Unofficial (Baileys) Integration

A side track that adds **unofficial WhatsApp Web** support as a second provider alongside the existing **Cloud API** integration. Customers can pair a personal/business WhatsApp number by scanning a QR (no Meta App, no WABA, no Embedded Signup) and use the same Conversations inbox the Cloud users already have.

This track is **purely additive**. The existing `whatsapp-platform-upgrade` track (Cloud API, Embedded Signup, templates, campaigns, business profile, automation) is untouched. Both providers coexist; per-org config picks which one is active.

---

## Why this track exists

Cloud API is the right product for serious customers — durable, compliant, scalable. But it has real friction:

- Meta Business Verification (1–5 business days)
- App Review submission (only required for production)
- Per-message billing once the free tier is exhausted
- Templates needed for any out-of-session message
- Phone number has to be **dedicated** to WABA (can't be a personal WhatsApp)

For **SMB onboarding**, **demo flows**, **internal support inboxes**, and customers who already pay nothing today, the unofficial path is the only realistic answer:

- Scan QR with your phone → connected in 30 seconds
- Send free-text any time, no templates
- No Meta App, no business verification
- Zero per-message cost
- Use the same number you use personally

**Trade-offs (must be surfaced to the customer):**

- Unofficial = WhatsApp ToS grey area. Number can be **banned** without notice — especially under bulk / spam patterns.
- Library (`@whiskeysockets/baileys`) is reverse-engineered. WhatsApp protocol changes can break it for 24–48h until the maintainers ship a patch.
- No template approval flow. No 24h session window contract.
- Not suitable for OTP / payment confirmations / regulated industries.

The CRM positions the two providers honestly: **Cloud = reliable transactional, Web = casual conversations.**

---

## Strategic position

| Need | Right provider |
|---|---|
| OTPs, order confirmations, payment receipts | **Cloud API** |
| Marketing campaigns at scale | **Cloud API** (template + ban-protected) |
| 1-click onboarding for a free-tier customer | **Web (Baileys)** |
| Support inbox using existing personal number | **Web (Baileys)** |
| Demo / pilot before Cloud verification completes | **Web (Baileys)** |
| Numbers in countries Cloud doesn't yet support | **Web (Baileys)** |

Per-org setting: an organisation can connect Cloud, Web, or **both** (different numbers).

---

## Architecture in 1 picture

```
┌────────────────────────────────────────────────────────────────────┐
│                  FastAPI CRM (Python) — unchanged                  │
│                                                                    │
│  core/conversations/ ← reused untouched                            │
│    ├─ models.py              tbl_conversations / tbl_messages      │
│    ├─ service.py             receive_webhook / send_outbound       │
│    └─ adapters/                                                    │
│       ├─ whatsapp.py         WhatsAppAdapter      (Cloud — exists) │
│       └─ whatsapp_web.py     WhatsAppWebAdapter   (Web — NEW)      │
│                                                                    │
│  core/integrations/                                                │
│    ├─ models.py              Integration (reused — new enum value) │
│    └─ whatsapp_web/          NEW module — connect / events         │
│       ├─ models.py           tbl_whatsapp_web_sessions (1 table)   │
│       ├─ router.py           /connect /disconnect /qr/stream       │
│       ├─ service.py          QR pairing flow + sidecar client      │
│       ├─ data_access.py      session CRUD                          │
│       ├─ sidecar_client.py   HTTPX wrapper, HMAC signing           │
│       └─ events.py           POST /events receiver (Baileys events)│
└────────────────────────────────────────────────────────────────────┘
                                     │
                         HTTP + HMAC │ (internal)
                                     ↓
                  ┌──────────────────────────────────────┐
                  │  sidecars/whatsapp-web/   (Node.js)  │
                  │                                      │
                  │  - Baileys WebSocket sessions        │
                  │  - QR pairing                        │
                  │  - Session credentials on disk       │
                  │  - Send / receive messages           │
                  │  - Reconnection + ban detection      │
                  │  - HMAC-signed event forwarder       │
                  └──────────────────────────────────────┘
                                     │
                                     ↓
                          wss://web.whatsapp.com
```

The Node sidecar is a **dumb transport pipe** — no business logic, no SQL, no tenant logic. FastAPI keeps every Conversations / Contacts / Automation rule.

---

## Reuse philosophy — what we DO and DON'T add

This track is fanatically reuse-first. Decisions made up-front so the implementation can't drift:

### Reused (zero changes)
- `tbl_contacts` — same contact rows, no provider discriminator.
- `tbl_conversations` — same `channel='whatsapp'` enum value. `received_via_phone_id` already exists (Step 27a from upgrade track) — Web sessions stamp their paired phone number there.
- `tbl_messages` — same `attachments` JSONB, `payload` JSONB, `channel_message_id`, `status` columns. Web's message id (Baileys `key.id`) goes in `channel_message_id` — same column the Cloud adapter uses.
- `core/conversations/service.py` — `receive_webhook` and `send_outbound` are channel-agnostic; we route through them unchanged.
- `core/conversations/adapters/__init__.py` — the `ChannelAdapter` Protocol + `InboundMessage` + `ChannelMessageRef` dataclasses fit Web exactly.
- `core/conversations/registry.py` — existing `register_channel` API; Web registers a parallel factory.
- `tbl_integrations` — same row shape; one new enum value (`whatsapp_web`).
- All Step 13 (notes), Step 14 (tags), Step 22 (opt-in), Step 23 (block list) features work unmodified on Web conversations.

### NOT duplicated (rejected on design)
- ❌ No `whatsapp_web_messages` table — `tbl_messages` already does this.
- ❌ No `whatsapp_web_chats` table — `tbl_conversations` already does this.
- ❌ No `whatsapp_web_contacts` table — `tbl_contacts` already does this.
- ❌ No parallel templates / campaigns / automation stack — Web doesn't support approved templates anyway, so the existing Cloud-only stack is irrelevant for Web (and stays correctly Cloud-only).
- ❌ No new conversation channel value. `channel='whatsapp'` for both providers; the `Integration.provider` row decides which adapter sends.
- ❌ No `whatsapp_web_account_configs` table. `Integration` row carries everything Web needs (paired phone in `account_label`, sidecar session id in `account_id`, status in `status`). The new sessions table is sidecar-state only.

### NEW (the minimum that's unavoidable)

**Backend code:**
- One new enum value: `IntegrationProvider.whatsapp_web` (1-line ALTER TYPE migration).
- One new table: `tbl_whatsapp_web_sessions` — sidecar session reference + transient pairing state. **5 columns total** (id, integration_id, sidecar_session_id, status, last_event_at). RLS-scoped via `TenantScoped` like every other table.
- One new module: `core/integrations/whatsapp_web/` — standard 5-file layered layout.
- One new adapter: `core/conversations/adapters/whatsapp_web.py` — implements `ChannelAdapter`, calls sidecar over HTTP.
- One dispatch shim in `core/conversations/service.py`: when sending an outbound WhatsApp message, pick the adapter by the org's `Integration.provider` (cloud vs web). **~10 lines.**

**Sidecar (new top-level folder):**
- `sidecars/whatsapp-web/` — TypeScript Node service. Exists outside `api/`. Owns Baileys.

**Frontend:**
- One new card on Settings → Integrations: **"WhatsApp Web (Unofficial)"** with QR pairing modal.
- Inbox / composer / contact / conversation UIs **completely unchanged** — they already render channel-agnostic messages.

That's the entire surface. No new permissions (reuses `settings.integrations.manage`). No new audit categories (reuses existing). No new sidebar entries.

---

## File map (final)

```
crm/
├── api/src/app/
│   ├── core/
│   │   ├── conversations/adapters/
│   │   │   └── whatsapp_web.py                 ← NEW (~150 lines)
│   │   ├── conversations/service.py            ← MODIFY (~10 lines: pick adapter)
│   │   └── integrations/
│   │       ├── models.py                       ← MODIFY (add whatsapp_web enum)
│   │       └── whatsapp_web/                   ← NEW module
│   │           ├── __init__.py
│   │           ├── models.py                   ← tbl_whatsapp_web_sessions
│   │           ├── schemas.py
│   │           ├── router.py
│   │           ├── service.py
│   │           ├── data_access.py
│   │           ├── sidecar_client.py
│   │           └── events.py
│   └── shared/config.py                        ← MODIFY (sidecar URL + HMAC secret)
├── alembic/versions/
│   └── 0117_whatsapp_web.py                    ← NEW (one migration)
├── app/src/app/features/user/core/
│   ├── settings/integrations/
│   │   └── whatsapp-web-card.component.ts      ← NEW (~120 lines)
│   └── settings/integrations/
│       └── whatsapp-web-qr-modal.component.ts  ← NEW (~100 lines)
└── sidecars/
    └── whatsapp-web/                           ← NEW top-level folder
        ├── package.json
        ├── tsconfig.json
        ├── Dockerfile
        ├── README.md
        └── src/
            ├── index.ts                        ← Express bootstrap
            ├── config.ts                       ← env loader
            ├── auth.ts                         ← HMAC verify/sign
            ├── logger.ts
            ├── sessions/
            │   ├── manager.ts                  ← Baileys lifecycle
            │   └── auth-store.ts               ← filesystem session storage
            ├── routes/
            │   ├── sessions.ts                 ← /sessions endpoints
            │   ├── messages.ts                 ← /send-text /send-media
            │   └── health.ts                   ← /health
            └── events/
                └── forwarder.ts                ← POST FastAPI /events
```

**Code budget:**
- Backend: ~600 lines net (1 new module + 1 adapter + 1 dispatch shim + 1 migration).
- Sidecar: ~800 lines TypeScript.
- Frontend: ~250 lines.

---

## Steps index

| # | Title | Goal | Effort |
|---|---|---|---|
| 1 | [Sidecar scaffold](step-01-sidecar-scaffold.md) | Node + Express + HMAC + health endpoint. No Baileys yet. | ~2 hrs |
| 2 | [Sidecar Baileys session manager + QR pairing](step-02-sidecar-baileys-session-manager.md) | Make / restore / destroy sessions, emit QR via event forwarder. | ~3 hrs |
| 3 | [Sidecar outbound send + inbound event forwarding](step-03-sidecar-send-and-events.md) | `/sessions/{id}/send-text` + `/send-media` + `messages.upsert` / `messages.update` forwarding. | ~3 hrs |
| 4 | [FastAPI migration + module skeleton](step-04-fastapi-migration-and-module.md) | Alembic: enum extension + `tbl_whatsapp_web_sessions`. Empty module skeleton. | ~1.5 hrs |
| 5 | [FastAPI connect / disconnect / status + sidecar client](step-05-fastapi-connect-and-sidecar-client.md) | `/whatsapp-web/connect` + `/disconnect` + `/status` + HMAC-signed HTTPX wrapper. | ~3 hrs |
| 6 | [FastAPI events receiver + SSE for QR](step-06-fastapi-events-and-sse.md) | `/whatsapp-web/events` (Baileys → FastAPI) + `/qr/{id}/stream` (FastAPI → frontend SSE). | ~3 hrs |
| 7 | [WhatsApp Web channel adapter + dispatch shim](step-07-channel-adapter-and-dispatch.md) | New adapter implementing `ChannelAdapter`. ~10-line shim in conversations service to pick adapter by provider. | ~2 hrs |
| 8 | [Frontend connect card + QR modal + smoke test](step-08-frontend-and-smoke.md) | "Connect WhatsApp Web" card on Settings → Integrations, QR pairing modal via SSE, end-to-end smoke flow. | ~3 hrs |

**Total: 8 steps. ~20 hours of code + ~half-day for E2E smoke + ban-handling tuning.**

Every step is independently reviewable (< 30 min). Steps 1–3 ship the sidecar in isolation (testable via curl + Postman). Steps 4–7 wire it into FastAPI. Step 8 closes the UI loop.

---

## The 10 non-negotiable rules — track-level self-check

1. **`/core` never imports from `/packs`.** ✅ This track is 100% core (`core/integrations/whatsapp_web/`). Pack-agnostic.
2. **Every table has `org_id` + RLS + `tbl_` prefix.** ✅ One new table `tbl_whatsapp_web_sessions`, scoped via `TenantScoped`, RLS policy in the migration.
3. **Custom fields layered model.** ✅ N/A — no entity-level custom fields here.
4. **Dynamic forms.** ✅ N/A — connect flow is a fixed QR pairing modal, not a custom-field form.
5. **Sidebar/menu is a registry.** ✅ No new sidebar entry. The connect card lives inside the existing Settings → Integrations page.
6. **Permissions are a registry.** ✅ No new permission keys. Reuses `settings.integrations.manage` (which already gates the WhatsApp Cloud connect card).
7. **`pack.yaml` source of truth.** ✅ N/A — Web is a platform-level provider, not a pack-specific feature.
8. **Step size small + human-verifiable.** ✅ 8 steps, each < 10 files / < 400 lines. Sidecar scaffold + Baileys are isolated (one folder, one process).
9. **No skipping verification.** Each step file has its own Stop & Report block — proceed only after human approval.
10. **No TODOs / hacks / dead code.** Sidecar code is production-shaped from day one (Dockerfile, structured logging, HMAC, retry queue, reconnect-on-disconnect).

---

## Risks + how the design mitigates them

| Risk | Mitigation |
|---|---|
| **Ban on the paired number** | Per-session outbound rate cap (1 msg/sec, 250 msgs/day until 30 days of "good behaviour"). Spam-pattern detector in sidecar rejects repeat-content bursts. Web rows always show a "Unofficial — at-risk" badge in the inbox. |
| **Baileys breaks on a WhatsApp protocol update** | Sidecar is in its own process / container — failure does not crash FastAPI or block Cloud sends. Bump `@whiskeysockets/baileys` independently. Health endpoint surfaces "library out-of-date" status in the Integrations card. |
| **Sidecar restart loses paired sessions** | Baileys credentials persisted to `./storage/sessions/{org_id}/{session_id}/` via `useMultiFileAuthState`. Sidecar boot loop re-instantiates every saved session — operator never re-scans QR after a deploy. |
| **HMAC secret leak** | Secret rotated by `run secrets-edit`. Sidecar HMAC keys read from `secrets.enc.env` (SOPS-encrypted, same pattern as Cloud `WHATSAPP_APP_SECRET`). |
| **Session storage at rest is sensitive** | Filesystem permissions: only sidecar user readable. Sessions folder under `./storage/` (same gitignored convention as media). Future hardening: encrypt creds with org-specific Fernet key — `auth-store.ts` is interface-driven so swap is a 50-line PR. |
| **Customer assumes Web = OTP-ready** | UI copy is explicit on the connect card ("Use Cloud API for transactional sends — Web can be banned without notice"). Templates page hides the "Send via WhatsApp Web" option. Campaign create modal refuses Web-only orgs with a clear "Connect Cloud API to run campaigns" prompt. |
| **Bulk send abuse from a tenant** | Per-org throughput cap enforced in sidecar before reaching WhatsApp. Mirrors the existing `WhatsAppAccountConfig.rate_limit_per_sec` cap pattern. |

---

## Where this slots in vs `whatsapp-platform-upgrade`

The Cloud track is the **canonical** WhatsApp integration. This track adds a second provider behind the same channel. Both can coexist on the same org (e.g. Cloud on the business number, Web on the founder's personal phone for VIP support).

| Feature | Cloud (existing) | Web (this track) |
|---|---|---|
| Connect flow | Embedded Signup / manual paste | QR scan |
| Inbox | Yes (existing) | Yes (reused) |
| Outbound text | Yes | Yes (new adapter) |
| Outbound media | Yes (Step 5) | Yes (Step 3 of this track) |
| Interactive buttons / list / CTA | Yes (Step 6) | ❌ Not supported by Baileys |
| Templates | Yes (Steps 8–10) | ❌ Not applicable |
| Campaigns | Yes (Step 3.5) | ❌ Blocked by design (ban risk) |
| Auto-reply / keyword / AI | Yes (Steps 16–19) | Yes (reused — engine is channel-agnostic) |
| Internal notes / tags / opt-in / block list | Yes (Steps 13/14/22/23) | Yes (reused) |
| Phone health dashboard | Yes (Step 12) | ❌ N/A — Baileys has no Meta tier |
| Click-to-WhatsApp attribution | Yes (Step 24) | ❌ N/A — no Meta Ads coupling |
| Multi-number per org | Yes (Step 27a) | Yes (multiple sessions, same pattern) |
| Reactions / quoted replies | Yes (Step 7) | Yes (Baileys supports both natively) |

---

## How to use this folder

1. **Always work the next pending step in order.** Steps 1–3 (sidecar) must land before Steps 4+ (FastAPI integration) — the FastAPI module assumes the sidecar's HTTP contract.
2. Open the step file. It is self-contained — goal, scope, files to touch, DB changes, tests, verification checklist, 10-rule self-check.
3. Implement only what the step file says.
4. Update the step's status in this README (Pending → In Progress → Done).
5. Wait for the human to say "proceed" before opening the next step file.

## Not in scope for this track

- WhatsApp **Business app** (different from WhatsApp Web — has its own multi-device protocol; out of scope, may revisit).
- Multi-device pairing beyond the standard Baileys flow.
- Voice / video calls — Baileys has experimental support; ban risk on non-text is even higher, deferred.
- Status updates / "stories" — out of scope.
- Group messaging — explicitly deferred. CRM use case is 1:1 conversations with contacts.
- Channel migration tool (move history from Cloud → Web or vice versa) — not needed; conversations stay on whichever provider received them.
