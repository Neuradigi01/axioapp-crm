# WhatsApp Platform Upgrade

A multi-phase track that upgrades Core CRM's WhatsApp surface from a manual-config MVP to a best-in-class integrated WhatsApp module — closing the feature gap vs Wati / Interakt (BSPs) and HubSpot / Salesforce / Zoho (vertical CRMs), while staying on the **BYO + Cloud API** architecture (no BSP, no virtual numbers, no per-message liability).

## Why this track exists

Today (audit date 2026-06-19), Core CRM's WhatsApp module is a working but minimal MVP:

- ✅ Connect with manual 5-field paste (phone_id, waba_id, access_token, app_secret, verify_token)
- ✅ Receive text + media (image/video/audio/document) → Conversations inbox
- ✅ Send text + approved templates (with `{{n}}` variables)
- ✅ Delivery / read / failed status tracking
- ✅ Per-org send-capacity token bucket + rate limit
- ✅ Campaign broadcasts with audience filters + schedule + quota checks
- ✅ Unified inbox + assignment + Mine/Unassigned filters

**Gaps that hurt customers today:**
- ❌ 5-field paste = ~90% onboarding drop-off — should be a 1-click Embedded Signup popup (Intercom/HubSpot pattern)
- ❌ No outbound media send (image/doc/PDF) — code comment says "deferred"
- ❌ No interactive messages (buttons / list) — industry standard since 2021
- ❌ Templates are read-only sync from Meta — customer must use Meta dashboard to create/edit/submit
- ❌ No business profile editor — display name, hours, description all require Meta Business Manager trips
- ❌ No internal notes, tags, reply/quote on conversations — table-stakes inbox features missing
- ❌ No phone quality / messaging-tier dashboard — customer flies blind on number health
- ❌ `ai_handling` field exists on conversations but is **not wired** to anything — biggest unrealized differentiator
- ❌ No welcome / out-of-hours / keyword auto-responder — every BSP has this
- ❌ No analytics dashboard (volume, response time, template perf, conversion)
- ❌ No DPDP compliance surface (opt-in capture, DND, block list)
- ❌ Click-to-WhatsApp ad attribution missing despite Meta Ads OAuth already wired
- ❌ No WhatsApp Flows (in-chat forms) — Meta's newest, most CRMs don't have it yet
- ❌ Single number per org lock — bigger customers blocked

## Strategic position

| Architecture | Onboarding | Margin | Path |
|---|---|---|---|
| Manual paste (today) | 1 week | High | — |
| **Embedded Signup + BYO** (this track) | 5 minutes | High | **Core CRM goes here** |
| BSP pool (Wati) | 1 day | Low (per-msg costs) | Rejected |

**Customer always pays Meta directly** for conversation charges (₹0.11–0.88 each). Core CRM platform pays **zero** to Meta — no hosting fees, no per-call charges, no App Review fees. Revenue = SaaS subscription only.

## Theme groupings (for reading; not enforced execution order)

| Theme | Steps | Why grouped |
|---|---|---|
| Embedded Signup (immediate next work) | 1-4 | Fixes onboarding drop-off; foundation for all later steps |
| Send richness | 5-7 | Outbound parity with Wati/HubSpot |
| Template management | 8-10 | Customer never opens Meta dashboard for templates |
| Business profile + phone health | 11-12 | Profile + quality dashboard |
| Conversation inbox upgrades | 13-15 | Multi-agent table stakes |
| Automation | 16-19 | Wires existing `ai_handling` field — biggest differentiator |
| Analytics | 20-21 | Manager-facing metrics |
| Compliance | 22-23 | DPDP / GDPR-ready |
| Strategic | 24-29 | Long-term moat vs competitors |

After Step 4, steps 5–29 each ship independently in any priority order.

## Steps index

| # | Title | Status | Effort |
|---|---|---|---|
| 1 | [Meta App configuration & prerequisites](step-01-meta-app-config.md) | **COMPLETED** — Configuration ID `1048461940853904` wired into `.env`; env vars in `.env.example` + `config.py`. Owner-side dashboard tasks (Business Verification, Required Actions, App Settings URLs) parallel-tracked, do not block code. | ~2 hrs |
| 2 | [Embedded Signup backend exchange endpoint](step-02-embedded-signup-backend.md) | **COMPLETED** — `POST /embedded-signup/exchange` + `GET /embedded-signup/config` wired in `whatsapp/router.py`; orchestration in `embedded_signup.py`; Meta Graph wrapper in `meta_graph_client.py`. | ~1.5 days |
| 3 | [Embedded Signup frontend popup flow](step-03-embedded-signup-frontend.md) | **COMPLETED** — Hero "Connect WhatsApp" button + Advanced (self-host) collapsible in `whatsapp-card.component.html`; `connectEmbedded()` handler in `whatsapp-card.component.ts`; FB SDK lifecycle in `whatsapp-fb-sdk.service.ts`. TypeScript check clean. | ~1 day |
| 4 | [Data deletion callback for Meta App Review](step-04-data-deletion-callback.md) | **COMPLETED** — Signed-request parser + endpoint in `meta/data_deletion.py`; `delete_meta_user_data` Celery task in `meta/tasks.py`; `MetaDataDeletionRequest` model + `Integration.meta_user_id` column; migration `0090_meta_data_deletion`; public `/data-deletion-status` page; 11+ pytest cases; operator docs in `API/docs/integrations/meta.md`. | ~3 hrs |
| 5 | [Outbound media send (image, video, audio, document)](step-05-outbound-media-send.md) | **COMPLETED** — `media_upload.py` (Meta `/media` multipart upload + MIME/size validation); WhatsApp adapter `send()` extended with media envelope branching (image/video/document carry caption, audio drops it); new `POST /conversations/{id}/messages/media` multipart route; composer paperclip + drag-and-drop + preview tile + per-type pre-validation; ng build clean; 14 pytest cases. | ~3 days |
| 6 | [Interactive messages (reply buttons + CTA + list)](step-06-interactive-messages.md) | **COMPLETED (code)** — `InteractivePayload` discriminated union (reply_buttons / cta_url / list) with per-kind char-limit enforcement; adapter `send()` builds Meta envelopes for all three; `parse_webhook` extracts `button_reply` + `list_reply` events into `attachments[]` reply attribution; interactive-builder modal with live preview + composer trigger; chat-thread renders buttons / list / CTA + "↳ Reply to:" attribution; ng build clean; 12 pytest cases. Migration `0091_messages_interactive` not yet applied — run `docker-helper.cmd upgrade` once DB is back. | ~2 days |
| 7 | [Reply / quote previous message + reactions](step-07-reply-quote-reactions.md) | Pending | ~1.5 days |
| 8 | [Template management backend (CRUD + Meta submit)](step-08-template-management-backend.md) | Pending | ~2.5 days |
| 9 | [Template builder UI (dedicated page + wizard)](step-09-template-builder-ui.md) | Pending | ~2.5 days |
| 10 | [Per-template performance card](step-10-template-performance-card.md) | Pending | ~1 day |
| 11 | [Business profile editor](step-11-business-profile-editor.md) | Pending | ~2 days |
| 12 | [Phone health & quality dashboard](step-12-phone-health-dashboard.md) | Pending | ~1.5 days |
| 13 | [Internal notes on conversations](step-13-internal-notes.md) | Pending | ~1 day |
| 14 | [Tags and labels on conversations](step-14-tags-labels.md) | Pending | ~2 days |
| 15 | [24-hour session window banner](step-15-session-window-banner.md) | Pending | ~1.5 days |
| 16 | [Welcome message + out-of-hours auto-reply](step-16-welcome-out-of-hours.md) | Pending | ~1.5 days |
| 17 | [Keyword triggers + auto-tagging](step-17-keyword-triggers.md) | Pending | ~1.5 days |
| 18 | [Auto-assignment rules](step-18-auto-assignment-rules.md) | Pending | ~1 day |
| 19 | [AI agent wiring on WhatsApp](step-19-ai-agent-wiring.md) | Pending | ~2 days |
| 20 | [Conversation analytics dashboard](step-20-conversation-analytics.md) | Pending | ~2 days |
| 21 | [Campaign analytics + cost + quality timeline](step-21-campaign-analytics.md) | Pending | ~2 days |
| 22 | [Opt-in capture (DPDP-ready)](step-22-opt-in-capture.md) | Pending | ~2 days |
| 23 | [DND / block list + conversation export](step-23-dnd-block-list.md) | Pending | ~1 day |
| 24 | [Click-to-WhatsApp ad attribution](step-24-click-to-whatsapp-attribution.md) | Pending | ~1.5 days |
| 25 | [WhatsApp Flows (in-chat forms)](step-25-whatsapp-flows.md) | Pending | ~3 days |
| 26 | [QR code generator + wa.me short links](step-26-qr-and-wa-me.md) | Pending | ~1.5 days |
| 27 | [Multi-number per org](step-27-multi-number-per-org.md) | Pending | ~2 days |
| 28 | [Edge inbound types (location, vCard, sticker)](step-28-edge-inbound-types.md) | Pending | ~1 day |
| 29 | [Campaign A/B testing](step-29-campaign-ab-testing.md) | Pending | ~2 days |

**Total: 29 steps. ~6 weeks of code + 1-3 weeks Meta App Review (overlaps Steps 1-4).**

Steps 1-4 are the immediate path to a working 1-click connect flow. Steps 5+ each independently shippable in any order once Steps 1-4 land.

## UI surfaces touched (page-by-page summary)

| Page | What changes | In which phase |
|---|---|---|
| Integrations page ([whatsapp-card.component.ts](APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.ts)) | 5-field form → 1-click Connect button + "Connected" state + phone health strip | Phase 1, 4 |
| Conversations inbox | Internal notes, tags, reply/quote, media compose, interactive send, template send, typing indicator, 24-hr session window banner, reactions | Phase 2, 5 |
| Templates (NEW dedicated page) | Create / edit / submit / duplicate / delete / performance card | Phase 3 |
| Campaigns | Template variable mapping UI, A/B toggle, cost preview, funnel chart, failure breakdown, per-recipient table | Phase 3, 7 |
| WhatsApp Business Profile (NEW sub-page) | Display name, description, hours, address, vertical, photo, greeting, away message, quick replies library | Phase 4 |
| Automation (NEW page) | Welcome / keyword / auto-assign / AI handover / auto-tag rule builders | Phase 6 |
| Reporting | New WhatsApp section: volume, response time, template perf, quality timeline, cost dashboard | Phase 7 |
| Contacts | Opt-in column + chip, DND toggle, last-interaction timestamp, "Message on WhatsApp" action, bulk import with opt-in | Phase 8 |
| Sidebar | Top-level WhatsApp entry with sub-items (Conversations · Templates · Campaigns · Automation · Business Profile · Analytics) | After Phase 6 |
| Dashboard | "WhatsApp" widget: X new messages, Y awaiting reply, Z campaigns scheduled | Phase 7 |
| Settings → Roles | Register new permission keys (whatsapp.connect, .business_profile.manage, .templates.*, .automation.manage, .analytics.read, .opt_in.manage) | Phase 6 (alongside Automation) |
| Audit log | New WhatsApp-specific events (integration connected/disconnected, template created/submitted, profile changed, auto-reply rule modified, opt-in revoked) | Throughout |

## Prerequisites (one-time, outside this codebase)

1. **Meta Business Verification** — should already be done for existing Meta Ads OAuth. Confirm via Meta Business Manager → Settings → Business Info → "Verified" badge.
2. **Privacy Policy URL + Terms URL** — public URLs required by Meta App Dashboard.
3. **App icon + display name** for the Meta App (shown in ES popup).
4. **One real WhatsApp Business number** owned by you (Neuradigi test number) for dev verification of the connect flow.
5. **ngrok / Cloudflare Tunnel** for local dev — Meta blocks `http://` in Embedded Signup, even on localhost.
6. **App Review submission** for `whatsapp_business_management` + `whatsapp_business_messaging` — Meta takes 1-3 weeks. Until approval, only added testers can complete the flow (dev/demo unblocked).

## Decisions locked

- **BYO (Bring Your Own Number) architecture.** Customer brings their own WhatsApp Business number. Core CRM is **not** a BSP. No virtual numbers issued, no per-message charges, no number procurement.
- **Embedded Signup configured to hide "Use a display name only" path.** Meta ES Configuration's `phone_number_selection` will be set so customers only see "connect your verified business number" — not virtual / display-name-only options.
- **Manual 5-field form kept as "Advanced (self-host)" fallback** for on-prem customers without Meta partner reach. Not the default surface.
- **App secret moves from per-org form input to server-side env var.** Meta best practice. Existing connected orgs grandfathered.
- **Multi-number per WABA deferred to Phase 9.** Phase 1 picks first phone number from WABA; document the limit in UI.

## Decisions deferred (open questions)

These are flagged for the user to answer **before** the relevant step begins — not blocking Phase 1.

- **AI agent wiring (Phase 6, Step 17):** which AI model backs the WhatsApp auto-responder? Existing `core/ai/` module — same model, or dedicated?
- **WhatsApp Flows (Phase 9, Step 23):** which 2-3 flows ship first? Recommended: lead capture form, appointment booking, customer feedback. Confirm before designing.
- **Sidebar promotion (after Phase 6):** does WhatsApp become a top-level sidebar entry with sub-items, or stay under Integrations? Recommend top-level (matches Conversations / Campaigns pattern).
- **Analytics retention:** how long do we keep raw conversation-level analytics? Recommend 13 months rolling; aggregate beyond that.

## Self-check against the 10 rules

- ✅ **Rule 1:** All work in `app/core/` (WhatsApp is a universal CRM channel, not furniture-specific). No `core/` → `packs/` imports.
- ✅ **Rule 2:** New tables (where needed) follow `tbl_` prefix + `org_id` + RLS. Existing `tbl_whatsapp_account_configs` already conforms.
- ✅ **Rule 3:** Custom fields engine untouched. Conversations use existing `custom_data` JSONB.
- ✅ **Rule 4:** New entity forms (templates, automation rules, business profile) render dynamically from field definitions where applicable.
- ✅ **Rule 5:** New sub-modules (templates, automation, business profile) registered via `ModuleDescriptor` / sidebar registry. Not hardcoded.
- ✅ **Rule 6:** New permission keys (`whatsapp.*`) registered via permission registry. Not bypassed.
- ✅ **Rule 7:** `pack.yaml` untouched — WhatsApp is core, not furniture-pack.
- ✅ **Rule 8:** Each step ≤ ~10 files / ≤ ~400 lines. Multi-day work (templates UI, automation) split into sub-steps.
- ✅ **Rule 9:** Each step has its own stop-and-report. Phases land sequentially.
- ✅ **Rule 10:** Production-ready; no TODOs / placeholders. Manual fallback kept clean as a separate path.

## Out of scope (intentionally)

- **BSP architecture** (managed phone number pool). Rejected — would compress margin, require Meta partner status, force Wati-reseller positioning.
- **WhatsApp Personal API** (greenwhats / unofficial APIs). Not Cloud API; carries account-ban risk. Cloud API only.
- **Furniture-pack-specific WhatsApp features** (catalog sync for sofas/beds, custom-order quote flows in chat). Belongs in `packs/furniture/`, not this core track.
- **SMS / Email channel work.** Conversations module supports multiple channels — those are separate tracks.

## What's enabled after this track

- **Customer onboarding: 1 week → 5 minutes.** Embedded Signup makes the WhatsApp module the easiest channel to set up.
- **Feature parity with Wati / Interakt** for inbox + send + templates + automation — but at SaaS pricing margins, not BSP markup.
- **Beyond Wati: AI agent on WhatsApp, in-chat Flows, click-to-WA ad attribution** — features dedicated WhatsApp tools don't have.
- **Core CRM positioned as a serious vertical CRM with first-class WhatsApp**, not "CRM + bolted-on WhatsApp tab."
