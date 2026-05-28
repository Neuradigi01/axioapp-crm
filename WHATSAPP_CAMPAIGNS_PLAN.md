# WhatsApp Campaigns — ChatJet-Style Build Plan

Branch: `Whatsapp-Inetgration` · Date: 2026-05-27

Yeh document FurnitureCRM ke campaigns module ko **ChatJet (`jet.aixoapp.com`) jaisa bulk-WhatsApp engine** banane ke liye ek detailed roadmap hai. Aapka goal hai: ek baar campaign banao → audience pick karo → bulk WhatsApp messages bhejo → delivery/read stats dekho.

Important — yeh document `tasks/` ke step files ka **replacement nahi** hai. Yeh ek planning/scoping doc hai. Real implementation ke time har feature alag step file mein break karenge (project ke 10-rule discipline ke according — ek step ≤10 files / ≤400 lines).

---

## 1. TL;DR — Aap kya bana rahe ho

Ek **bulk WhatsApp marketing/transactional broadcasting engine** jismein:

- Operator ek pre-approved Meta template + audience filter ya group + schedule pick kare.
- Engine audience resolve kare, Meta Cloud API ko throttled batches mein hit kare.
- Har contact ke liye `queued → sent → delivered → read` ya `failed` status track ho (live webhook se).
- Per-campaign analytics dashboard ho (audience, sent, delivered, read, failed, reply rate).
- Reply aaye toh conversation inbox mein land kare (already wired) aur optionally lead bane.

---

## 2. Abhi kya bana hua hai (Whatsapp-Inetgration branch ki state)

### Backend — `API/src/app/core/campaigns/`

| Piece | File | Status |
|---|---|---|
| `Campaign` model (name, channel, audience_filter JSONB, template, schedule_at, status, created_by) | [models.py](API/src/app/core/campaigns/models.py) | Done |
| `CampaignMessage` model (campaign × contact, channel_message_id, status, error, sent_at) | [models.py](API/src/app/core/campaigns/models.py) | Done |
| Status enums: `draft / scheduled / running / done / failed` (campaign) & `queued / sent / delivered / read / failed` (message) | [models.py](API/src/app/core/campaigns/models.py) | Done |
| CRUD + start + stats + retry + per-message list + pagination endpoints | [router.py](API/src/app/core/campaigns/router.py) | Done |
| Audience resolver — `q`/`source`/`tag` filter over `contacts` | [service.py](API/src/app/core/campaigns/service.py#L199-L226) | Done — but only 3 dimensions |
| Inline chunked dispatch (chunk size 50, sequential POSTs) | [service.py](API/src/app/core/campaigns/service.py#L232-L331) | Done — **Celery isn't wired yet**, runs inline |
| Mustache-style `{{full_name}}` / `{{phone}}` / `{{email}}` variables | [service.py](API/src/app/core/campaigns/service.py#L532-L551) | Done — only 3 vars |
| Outbound message also appears in Conversations inbox | [service.py](API/src/app/core/campaigns/service.py#L437-L450) | Done |
| Per-(campaign, contact) idempotency (unique index + `ON CONFLICT DO NOTHING`) | [service.py](API/src/app/core/campaigns/service.py#L334-L364) | Done |
| Permissions: `campaigns.read` / `campaigns.write` / `campaigns.send` | [router.py](API/src/app/core/campaigns/router.py) | Done |

### Backend — `API/src/app/core/conversations/adapters/whatsapp.py`

| Piece | Status |
|---|---|
| `WhatsAppAdapter.send(...)` — POSTs `type: text` to Meta Cloud API | Done |
| `WhatsAppAdapter.parse_webhook(...)` — pulls inbound message from Meta envelope | Done |
| `WhatsAppAdapter.verify_signature(...)` — HMAC-SHA256 on `X-Hub-Signature-256` | Done |
| `WhatsAppAdapter.verify_subscription(...)` — GET handshake | Done |
| Adapter registry — `register_default_whatsapp_adapter()` called at startup | Done |
| `register_default_whatsapp_adapter` reads env config (single tenant only) | Done — but **single tenant** |

### Frontend — `APP/src/app/features/user/core/campaigns/`

| Piece | File | Status |
|---|---|---|
| Campaigns list page (cards with status pill, channel pill, audience preview, schedule, Start/Delete) | [campaigns.page.ts/html](APP/src/app/features/user/core/campaigns/campaigns.page.ts) | Done |
| Create-campaign modal (name, channel, audience q/source/tag, template, schedule_at) | [create-campaign-modal.component.ts](APP/src/app/features/user/core/campaigns/create-campaign-modal.component.ts) | Done |
| Detail page — stats KPIs + per-message table + per-message retry + 5s polling | [campaign-detail.page.ts](APP/src/app/features/user/core/campaigns/campaign-detail.page.ts) | Done |
| API service wrapper | [campaigns-api.service.ts](APP/src/app/features/user/core/campaigns/campaigns-api.service.ts) | Done |

### Bottom line

Aapke paas ek **kaam karta hua MVP campaigns engine** already hai jo free-form text WhatsApp messages ko 50-contact batches mein bhej sakta hai. Lekin ChatJet-grade product ke liye **9 critical pieces** missing hain (next section).

---

## 3. ChatJet-style gaps — Kya kya banana padega

### Priority P0 (MVP-launch blockers)

#### 3.1 **WhatsApp Business Template (Meta-approved) support**

**Kyon critical:** Meta WhatsApp Cloud API par **business-initiated** messages (jaise marketing campaigns) **sirf pre-approved templates** se hi ja sakte hain. Free-form text sirf 24-hour customer-service window mein hi allowed hai (jab customer ne pehle msg bheja ho).

Abhi adapter `type: "text"` bhej raha hai — yeh Meta ke "Marketing/Utility template" rules ke under **block ho jayega** real production WhatsApp Business Account par.

**Kya banana hai:**

- **Backend:**
  - Naya model `whatsapp_templates` — `id, org_id, meta_template_name, language_code (e.g. en_US, hi), category (MARKETING/UTILITY/AUTHENTICATION), status (PENDING/APPROVED/REJECTED), components JSONB`.
  - Sync endpoint: `GET /api/v1/whatsapp/templates/sync` — Meta Cloud API se templates fetch karke local table mein cache kare.
  - `WhatsAppAdapter.send_template(...)` — `type: "template"` envelope: `{ name, language: {code}, components: [{ type: "body", parameters: [...] }] }`.
  - `Campaign` model mein `template_id` (FK to whatsapp_templates) + `template_variables` JSONB column. `template` (raw text) column ko backwards-compatible "free-form" mode ke liye rakhna.
- **Frontend:**
  - Create-campaign modal mein "Template" picker (dropdown of approved Meta templates).
  - Template preview (header/body/footer + buttons rendered like WhatsApp UI).
  - Variable mapping UI: har `{{1}}`, `{{2}}` ke liye dropdown "Map to: full_name / phone / custom_data.fav_collection / static text".

**Files (estimate):**
- `api/src/app/core/integrations/whatsapp/templates.py` (model + service + router)
- `api/alembic/versions/00XX_whatsapp_templates.py`
- `api/src/app/core/conversations/adapters/whatsapp.py` — add `send_template`
- `api/src/app/core/campaigns/service.py` — branch text vs template in `dispatch_chunk`
- `app/.../campaigns/template-picker.component.ts`
- `app/.../campaigns/create-campaign-modal.component.ts` — extend form

---

#### 3.2 **Contact import (XLSX / CSV)**

**Kyon critical:** Operator ko har contact manually CRM mein add karna unrealistic hai. ChatJet ka killer feature yahi hai — XLSX upload se hazaron contacts ek baar mein import.

**Kya banana hai:**

- **Backend:**
  - `POST /api/v1/contacts/import` — multipart upload (xlsx/csv), validate, dry-run preview, then commit.
  - Column mapping endpoint: client uploads → server returns detected columns → user maps to contact fields (full_name, phone, email, source, tags, custom_data.* etc).
  - Phone E.164 normalization (already partially in `whatsapp.py:_normalize_phone`, lift it to a shared util).
  - Duplicate handling: `phone` ya `email` already exists → skip / update / create-anyway choice.
- **Frontend:**
  - 3-step wizard: Upload → Map columns → Preview & commit.
  - Per-row error display (row 47: invalid phone, row 88: missing required column).
  - Background job + progress bar for >5000 rows (uses notifications system).

**Files:** ~6-8 files. Reuse `openpyxl` (Python) for XLSX, native CSV module.

---

#### 3.3 **Saved contact groups / segments**

Abhi audience ad-hoc filter (`{q, source, tag}`) hai. ChatJet mein "VIP Customers", "Diwali 2024 walk-ins", "Bangalore Showroom" jaise **named groups** hain jinhe baar-baar reuse kar sako.

**Kya banana hai:**

- **Backend:**
  - `contact_groups` table — `id, org_id, name, definition JSONB (extended filter shape), is_dynamic boolean, created_at, updated_at`.
  - `contact_group_members` table — sirf **static groups** ke liye (`group_id, contact_id, added_at`). Dynamic groups query-on-the-fly.
  - CRUD endpoints + "preview audience" endpoint (count of matching contacts).
  - `Campaign.audience_filter` → can now also be `{group_id: "..."}`.
- **Frontend:**
  - Naya page `/user/contacts/groups` — list + create/edit groups.
  - Campaign create modal mein audience selector: "Everyone / Named group / Custom filter".

**Files:** ~8 files (backend + frontend).

---

#### 3.4 **Delivery / read webhook → status update**

Abhi WA adapter sirf inbound messages parse karta hai. Meta webhook `delivered` / `read` notifications bhi bhejta hai (`statuses[]` array) — yeh capture nahi ho rahe, isliye campaign detail page hamesha "sent" hi dikhati hai, "delivered ✓✓" / "read ✓✓ blue" nahi.

**Kya banana hai:**

- **Backend:**
  - `WhatsAppAdapter.parse_webhook` ko extend karke `statuses` payload bhi parse kare → return karo ek `[StatusUpdate]` list (`channel_message_id, status, timestamp, error_code, error_title`).
  - `conversations/service.py` ya new `campaigns/webhook_handler.py` mein status updates ko match karein `channel_message_id → CampaignMessage` aur status update karein.
  - Add `delivered_at, read_at` columns to `campaign_messages` (currently only `sent_at`).
- **Frontend:** No work — detail page already polls stats.

**Files:** ~3-4 files + 1 migration.

---

#### 3.5 **Celery worker / async dispatch**

Abhi `enqueue` inline chalata hai — 5000-contact campaign API request ko 5 minute tak block karega (50-contact chunks × 100 chunks × 0.5s each).

**Kya banana hai:**

- `api/celery_app.py` (already-planned stub) ko wire karo, `CELERY_ENABLED=true` env flag.
- `tasks/send_campaign_chunk.py` — `send_campaign_chunk.delay(campaign_id, contact_ids)`.
- `service.enqueue` swap inline loop for `.delay(...)`.
- Redis broker config (already in stack).
- Celery beat scheduler for `schedule_at`-based campaigns (poll `status='scheduled' AND schedule_at <= now()` every minute).

**Files:** ~4 files. Pehle se step plan mein hai (Phase 5).

---

#### 3.6 **Throttling / rate limiting**

Meta tier limits:
- Tier 1: 1K business-initiated conversations/24h
- Tier 2: 10K
- Tier 3: 100K
- Tier 4: Unlimited

Bina throttle ke aap Meta se ban kha sakte ho. Solution:

- Per-org config: `whatsapp_send_rate_per_minute` (e.g. 60 = 1/sec).
- Celery task `send_campaign_chunk` mein `asyncio.sleep()` ya token-bucket between sends.
- Failed-with-429 retry with exponential backoff.

**Files:** Mostly extends 3.5 above.

---

### Priority P1 (post-MVP polish)

#### 3.7 **Multiple WhatsApp sender numbers (multi-tenant config)**

Abhi `WHATSAPP_PHONE_ID` / `WHATSAPP_TOKEN` env-vars hain — ek hi number poore platform ke liye. SaaS ke liye **per-org config** chahiye:

- `whatsapp_business_accounts` table — `id, org_id, display_name, phone_id, access_token (encrypted), app_secret (encrypted), verify_token, default_for_org boolean, status (active/inactive)`.
- `WhatsAppAdapter` ko `org_id` aware banao — adapter factory load config from DB.
- Settings page `/user/settings/integrations/whatsapp` — connect/test/disconnect.

#### 3.8 **Media attachments in campaigns**

Image / video / document ke saath bhejna. Media upload to Meta first (returns media_id), then reference in template.

- Backend: `POST /api/v1/whatsapp/media/upload` proxy.
- Frontend: file picker in create modal.
- Note: Meta-approved templates **must** have media placeholders in header.

#### 3.9 **Per-contact opt-out / DND**

WhatsApp business policy mandate. User "STOP" / "UNSUBSCRIBE" likhe toh wo opt-out.

- Add `wa_opt_out_at` column to `contacts`.
- Inbound webhook auto-detect "STOP" → set flag.
- `resolve_audience` mein `WHERE wa_opt_out_at IS NULL` add karo.
- Settings: opt-out keyword config.

#### 3.10 **Personalization with custom_data**

Aaj `{{full_name}}` / `{{phone}}` / `{{email}}` hi support hai. CRM mein `custom_data` JSONB column hai (Rule 3 — layered custom fields). Extend `_render_template` to support `{{custom_data.fav_collection}}` etc.

#### 3.11 **Test send / preview**

"Send to me" button — operator apne phone par test bhej sake before mass send.

#### 3.12 **CSV export of message status**

`GET /api/v1/campaigns/{id}/messages.csv` — `phone, name, status, sent_at, delivered_at, read_at, error`. Operator post-mortem ke liye chahiye.

---

### Priority P2 (nice-to-have)

| Feature | One-liner |
|---|---|
| Interactive buttons | Quick-reply + URL + phone CTA buttons (Meta template components) |
| A/B variants | 2-3 template variants, split traffic, declare winner |
| Recurring campaigns | Daily/weekly cron-style schedule |
| Click tracking | URL redirector counts per-contact clicks |
| Auto lead-creation | If reply received & no existing lead → create lead, assign |
| Campaign clone | "Duplicate from this campaign" button |
| In-app saved templates | Reusable text/template library (separate from Meta-approved) |
| Variable validation | "23/100 contacts missing field X — skip or fix?" before send |
| Sender pool | Auto-rotate across multiple sender phone numbers |
| Reply handling routing | Configurable "campaign replies go to user/team Y" |

---

## 4. Recommended phasing

Master prompt ka Rule 9 (no skipping verification) follow karte hue, har P0 feature **alag step file** banega `tasks/phase-3-communication-staff/` ya naya `tasks/phase-3.5-whatsapp-campaigns/` mein:

### Phase A — WhatsApp template foundation (P0)
1. **Step CA.1** — `whatsapp_templates` table + Meta sync endpoint + admin UI to view templates.
2. **Step CA.2** — `WhatsAppAdapter.send_template(...)` + adapter unit tests.
3. **Step CA.3** — Campaign create modal mein template picker + variable mapper.
4. **Step CA.4** — Dispatch path branch: text vs template in `dispatch_chunk`.

### Phase B — Audience tooling (P0)
5. **Step CA.5** — `contact_groups` + `contact_group_members` tables + CRUD + preview-audience endpoint.
6. **Step CA.6** — Contacts groups frontend page.
7. **Step CA.7** — Campaign create modal mein "Everyone / Group / Custom filter" toggle.
8. **Step CA.8** — XLSX/CSV contact import backend (upload + parse + dry-run).
9. **Step CA.9** — XLSX/CSV contact import frontend wizard.

### Phase C — Delivery telemetry (P0)
10. **Step CA.10** — `delivered_at` / `read_at` columns + webhook `statuses[]` parsing + `CampaignMessage` update.
11. **Step CA.11** — Campaign detail page mein delivered/read ticks (✓ / ✓✓ / ✓✓ blue).

### Phase D — Scale & reliability (P0)
12. **Step CA.12** — Celery worker wired + `send_campaign_chunk.delay()` + beat for scheduled.
13. **Step CA.13** — Per-org rate limit + 429 backoff + retry policy.

### Phase E — Polish (P1)
14. **Step CA.14** — Per-org WhatsApp Business Account config + settings UI.
15. **Step CA.15** — Media attachments + media upload proxy.
16. **Step CA.16** — Opt-out flag + "STOP" auto-detect.
17. **Step CA.17** — `custom_data.*` variable substitution.
18. **Step CA.18** — Test send + CSV export.

### Phase F — Extras (P2, on demand)
- Interactive buttons, A/B, recurring, click tracking, etc.

---

## 5. Open decisions (aap batao before code likhna)

1. **Meta WhatsApp Business Account setup** — Kya aapne `business.facebook.com` par WABA register kiya hai? Phone number verified? App in "Live" mode hai ya "Development"? Test number se shuru karenge ya production se?

2. **Templates pehle se hain?** — Kya `business.facebook.com → WhatsApp Manager → Templates` mein approved templates hain? Agar haan, ek "Hello {{1}}" basic template approve karwa lo — Phase A ki testing usse hogi.

3. **Tenancy model** — MVP ke liye single-tenant (ek WhatsApp number puri demo org ke liye) chalega? Ya day-1 multi-tenant chahiye? Single-tenant fast hoga, multi-tenant 1 extra step (3.7).

4. **Celery infra** — Redis abhi running hai dev mein? Agar nahi, Phase D ke time aapko `docker-compose up redis` chalana hoga (config already mentions Redis).

5. **Throttle defaults** — Default rate 60 msg/min (1/sec) thik hai? Ya higher (Tier 2 WABA hai)?

6. **Audience filter semantics** — Aaj filter `q + source + tag` hai. ChatJet jaisa rich filter chahiye? (`created_after`, `last_purchase_amount > X`, `tag IN (...)`, `assigned_to_id = ...`)? Yeh decide karo before Step CA.5.

7. **Opt-out copy** — "STOP" keyword fixed rakhna hai ya per-org configurable (e.g. "BAND KARO")?

8. **Conversations integration** — Already campaign outbound msgs inbox mein dikh rahe hain. Replies bhi automatically wahi route ho rahe hain. Koi additional routing chahiye (e.g. "campaign X ke replies sirf user Y ko dikhao")?

---

## 6. Quick reference — Existing files aap touch karoge

### Backend
- [API/src/app/core/campaigns/models.py](API/src/app/core/campaigns/models.py) — add `template_id`, `template_variables`, `delivered_at`, `read_at`.
- [API/src/app/core/campaigns/service.py](API/src/app/core/campaigns/service.py) — extend `dispatch_chunk` (text vs template), `_render_template` (custom_data), `resolve_audience` (groups + opt-out).
- [API/src/app/core/campaigns/router.py](API/src/app/core/campaigns/router.py) — new endpoints for test-send, CSV export, audience preview.
- [API/src/app/core/conversations/adapters/whatsapp.py](API/src/app/core/conversations/adapters/whatsapp.py) — add `send_template`, extend `parse_webhook` for `statuses[]`, multi-tenant config loader.
- New: `API/src/app/core/integrations/whatsapp/templates.py`, `API/src/app/core/contacts/groups.py`, `API/src/app/core/contacts/import_service.py`.

### Frontend
- [APP/src/app/features/user/core/campaigns/create-campaign-modal.component.ts](APP/src/app/features/user/core/campaigns/create-campaign-modal.component.ts) — template picker, variable mapper, audience selector toggle, media upload, test-send button.
- [APP/src/app/features/user/core/campaigns/campaign-detail.page.ts](APP/src/app/features/user/core/campaigns/campaign-detail.page.ts) — delivered/read ticks, CSV export button.
- New: `APP/src/app/features/user/core/campaigns/template-picker.component.ts`, `audience-builder.component.ts`.
- New page tree: `APP/src/app/features/user/core/contacts/groups/`.
- New page tree: `APP/src/app/features/user/core/contacts/import/`.
- New: `APP/src/app/features/user/core/settings/integrations/whatsapp/` (Phase E).

### Database migrations
- `whatsapp_templates` table
- `whatsapp_business_accounts` table (Phase E)
- `contact_groups` + `contact_group_members` tables
- `campaign_messages.delivered_at`, `.read_at` columns
- `campaigns.template_id`, `.template_variables` columns
- `contacts.wa_opt_out_at` column (Phase E)

---

## 7. Effort estimate (rough)

| Phase | Steps | Est. duration (with verification gates) |
|---|---|---|
| Phase A — Templates | 4 steps | 3-4 working days |
| Phase B — Audience tooling | 5 steps | 4-5 working days |
| Phase C — Delivery telemetry | 2 steps | 1-2 working days |
| Phase D — Scale | 2 steps | 2 working days |
| **MVP total (A+B+C+D)** | **13 steps** | **10-13 working days** |
| Phase E — Polish (P1) | 5 steps | 4-5 working days |
| Phase F — Extras (P2) | on demand | — |

---

## Aage kya?

Mujhe section 5 ke **8 open decisions** ke jawab batao. Uske baad mai **Step CA.1** (`whatsapp_templates` table + Meta sync endpoint) ka detailed task file `tasks/phase-3-communication-staff/step-3.X-whatsapp-templates-sync.md` mein likhke aapko show karunga — phir aap "begin Step CA.1" bolo aur hum chalu kar denge, project ke 10-rule discipline ke according.
