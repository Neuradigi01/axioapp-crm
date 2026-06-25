# Central Template Library

A new core module that **promotes templates out of WhatsApp + Settings** into a standalone, multi-channel library — sibling to Contacts, Campaigns, Conversations. Mirrors the standard CRM pattern (HubSpot Marketing Library / Zoho Content Library / Salesforce Marketing Cloud Content Builder).

## Why this track exists

Today (audit date 2026-06-24), templates live in two disconnected places:

- **WhatsApp templates** — `core/integrations/whatsapp/templates_*.py` + `app/.../whatsapp/templates/` UI. Full Meta-approval pipeline, lives under the WhatsApp module.
- **Email templates** — `core/email_templates/` + `app/.../settings/email-templates/` UI. Buried under **Settings → Email Templates**.

There is no central library, no internal review workflow, no support for other channels (SMS, FB Messenger, IG Direct, push), and campaigns hard-FK to WhatsApp-only templates (`tbl_campaigns.template_id → tbl_whatsapp_templates`).

**Manager spec 2026-06-24:** one unified library with `draft → in_review → approved → published → archived` workflow that applies to every channel, plus external-provider status (Meta WA approval, future SMS-DLT registration) visible inside our app. Campaigns + email_sequences both consume the same generic `template_id`. Sequences UI stays in Settings for now and migrates in the future `tasks/workflows/` track.

## What changes

- New `core/templates/` module — backend models, service, router, internal review state machine, external-status sync, per-channel test send.
- New `app/.../core/templates/` UI — top-level sidebar entry. List + channel-aware editor + review modal + versions drawer.
- Existing `core/email_templates/` is **merged in** (not parallel). Settings → Email Templates tab is removed.
- Existing `tbl_whatsapp_templates` stays as a polymorphic extension for Meta-specific fields (header type, button payloads, language code, components JSON) — linked via `tbl_message_templates.external_provider_id`. Existing WA template UI deep-links into the new module filtered by `channel=whatsapp`.
- `tbl_campaigns.template_id` and `tbl_email_sequences.template_id` both switch to FK `tbl_message_templates.id`.
- `core/email_sequences/` keeps its UI in Settings (moves out only when the future `tasks/workflows/` track lands). FK switch happens here.

## What this track does NOT include

- **Event-trigger automation** (welcome email on signup, lead.created → confirmation) — that's `tasks/automation-engine/`, the next track.
- **Multi-step branching workflows** (HubSpot Workflows / Salesforce Journey Builder) — future `tasks/workflows/` track, which will also absorb `core/email_sequences/`.
- **Deliverability infrastructure** (SPF / DKIM / DMARC status, bounce webhook handlers, suppression list) — lives in `tasks/automation-engine/` (send-time enforcement step).
- **SMS provider integration** (Gupshup / MSG91 / Kaleyra OAuth + DLT submission). SMS sub-form ships here; actual send is gated on a future SMS-channel track.
- **FB Messenger / IG Direct / push channel adapters themselves.** Sub-forms ship; sends are no-op stubs until those channel tracks happen.

## Multi-tenancy

Every new table has `org_id` UUID FK to `tbl_organizations` and Postgres RLS from the migration that creates it. Every API call resolves `org_id` from JWT context; every variable resolver (`{{contact.first_name}}`, `{{org.name}}`) is tenant-scoped. Meta external template IDs are unique per WABA, not globally — each org connects its own WABA and tracks its own submissions.

## Theme groupings

| Theme | Steps | Why grouped |
|---|---|---|
| Schema + backend core | 1-3 | Tables, models, service layer, router |
| Review workflow + test send | 4-5 | Internal state machine + per-channel test send + sidebar registration |
| Frontend | 6-8 | List page, editor (WA + Email), review/versions UI |
| Channel migrations | 9-10 | WhatsApp rehoused, Email merged in, Settings tab dropped |
| Consumer refactor | 11 | Campaigns switches to generic `template_id` |
| New-channel stubs | 12-13 | SMS / FB / IG / push sub-forms + stub adapters |
| Polish | 14 | External status sync periodic task + UI badges + webhook updates |

Steps 1-8 ship the new module end-to-end with only WA + Email channels usable. Steps 9-14 migrate and extend.

## Steps index

| # | Title | Status | Effort |
|---|---|---|---|
| 1 | [Templates schema + models](step-1-templates-schema-and-models.md) | **COMPLETED** | ~0.5 days |
| 2 | [Templates service + variable engine](step-2-templates-service-and-variables.md) | **COMPLETED** | ~1 day |
| 3 | [Templates router + permissions](step-3-templates-router.md) | **COMPLETED** | ~0.5 days |
| 4 | [Internal review workflow](step-4-internal-review-workflow.md) | **COMPLETED** | ~1 day |
| 5 | [Test send + sidebar registration](step-5-test-send-and-sidebar.md) | **COMPLETED** | ~0.5 days |
| 6 | [Templates list UI](step-6-templates-list-ui.md) | **COMPLETED** | ~1 day |
| 7 | [Templates editor UI (WA + Email sub-forms)](step-7-templates-editor-ui.md) | **Pending** | ~1.5 days |
| 8 | [Review modal + versions drawer + test-send modal](step-8-templates-review-and-versions-ui.md) | **Pending** | ~1 day |
| 9 | [WhatsApp adapter migration](step-9-whatsapp-adapter-migration.md) | **Pending** | ~1 day |
| 10 | [Email templates merge + UI move](step-10-email-templates-merge-and-ui-move.md) | **Pending** | ~1 day |
| 11 | [Campaigns refactor — generic template_id](step-11-campaigns-refactor.md) | **Pending** | ~1 day |
| 12 | [SMS adapter stub + DLT fields](step-12-sms-adapter-stub.md) | **Pending** | ~0.5 days |
| 13 | [FB / IG / push sub-forms + stub adapters](step-13-fb-ig-push-adapter-stubs.md) | **Pending** | ~0.5 days |
| 14 | [External status sync — Celery + webhook + UI badges](step-14-external-status-sync-polish.md) | **Pending** | ~1 day |

**Total: 14 steps, ~11.5 days.**

After this track closes, `tasks/automation-engine/` opens — single-event triggers (`user.signed_up` → welcome email, `lead.created` → confirmation, etc.) consuming this library.

## UI surfaces touched

| Page | What changes | In which step |
|---|---|---|
| Sidebar | New top-level "Templates" entry (Manager+ visible; Employee author-only) | Step 5 |
| Templates list (NEW) | List + channel filter + status filter + status badges (internal + Meta external) | Step 6 |
| Template editor (NEW) | Channel-aware sub-forms (WA / Email / SMS / FB-IG / push), variable picker, live preview | Steps 7, 12, 13 |
| Template review modal (NEW) | Reviewer note + approve/reject/request-changes | Step 8 |
| Template versions drawer (NEW) | Full version history + diff view | Step 8 |
| Template test-send modal (NEW) | Per-channel test send to self / nominated recipient | Step 8 |
| WhatsApp module | Existing `/user/whatsapp/templates` deep-links into new module filtered by `channel=whatsapp` | Step 9 |
| Settings → Email Templates tab | **Removed.** | Step 10 |
| Settings → Email Sequences tab | Untouched (moves in future `tasks/workflows/` track). FK switches behind the scenes. | Step 10 |
| Campaign create modal | Template picker switches to generic; channel filter applied automatically | Step 11 |
| Settings → Roles | Five new permission keys registered (`templates.read / write / review / publish / submit_external`) | Step 3 |

## The 10 rules — track-wide notes

- **Rule 1** (core never imports packs): Templates module is pure `core/`. No furniture pack hooks. ✓
- **Rule 2** (org_id + RLS): every new table — `tbl_message_templates`, `_versions`, `_reviews`, `_assets`, `_test_sends` — has `org_id` FK + RLS policy from its first migration. ✓
- **Rule 3** (custom fields): N/A — templates don't expose custom fields to end users.
- **Rule 4** (dynamic forms): N/A — template editor is static (channel sub-forms are part of the module).
- **Rule 5** (sidebar registry): new sidebar entry registered via `module.py` in Step 5. Core doesn't hardcode it.
- **Rule 6** (permission registry): five new permission keys registered in Step 3.
- **Rule 7** (pack.yaml): no furniture defaults change. ✓
- **Rule 8** (step size): every step ≤ ~10 files / ~400 lines, individually shippable.
- **Rule 9** (no skipping verification): stop-report after each step.
- **Rule 10** (no TODOs): every step leaves the codebase clean and runnable.
