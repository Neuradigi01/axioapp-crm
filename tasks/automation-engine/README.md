# Automation Engine

A new core module that adds **event-triggered automation** to Core CRM — single-event triggers like "user signed up → send welcome email", "lead created → send confirmation". Consumes the central template library from `tasks/template-library/`. Mirrors the standard CRM pattern (HubSpot single-step automations / Zoho Workflow Rules / Salesforce Process Builder triggers).

## Why this track exists

After `tasks/template-library/` ships, the CRM has a unified template library but **no automatic sends** — every template still goes out via manual send, drip enrolment, or campaign launch. Manager directive 2026-06-24:

- **"Welcome mail at the same"** — when a user signs up, send a welcome email automatically.
- **"Mail to lead automatically when the lead id submitted via anywhere"** — every lead-capture source (form widget, Google Ads webhook, Meta Ads webhook, bulk import, manual entry, WhatsApp inbound, walk-in, API) must fire a confirmation email.

That's an event-trigger engine — what HubSpot calls "Workflows", Salesforce calls "Process Builder", Zoho calls "Workflow Rules". This track builds it.

## What it does

- Internal pub/sub event bus. CRM modules publish domain events (`user.signed_up`, `lead.created`, `appointment.booked`, `quote.sent`, `invoice.overdue_7d`, `contact.birthday`, `lead.stale_30d`, etc.) onto the bus.
- Trigger registry: each org configures `trigger = event + conditions + template + delay + recipient_resolver`. When the event fires, the engine matches enabled triggers and queues sends.
- Per-channel dispatch: each trigger picks a channel (email / WhatsApp / etc.) and renders through the central template library's variable engine + the channel adapter.
- Run history: every fire logged with payload + status + delivered/failed/skipped reason. Per-contact engagement timeline on contact detail.
- Settings → Automations sidebar entry: Owner toggles, edits, clones, and inspects each trigger.
- Default triggers seeded at org creation: User Welcome, Lead Confirmation. Owner can edit body, channel, delay, or disable entirely.
- Compliance baked in: DPDP suppression check, frequency cap (max N marketing/week/contact), quiet hours (default 9am-9pm IST per org tz), marketing vs transactional category separation (transactional ignores frequency cap + unsubscribe).
- Deliverability: bounce + complaint webhook handlers update the suppression list; DKIM/SPF status surfaced in Settings → Email so Owner sees domain warm-up readiness.

## What this track does NOT include

- **Multi-step branching workflows** (HubSpot Workflows / Salesforce Journey Builder visual flowchart with IF/ELSE, goals, re-engagement loops) — future `tasks/workflows/` track. This track is single-event-fires-one-template only.
- **Drip sequence enrolment-from-triggers** (e.g. "on lead.created, enrol in 5-step nurture sequence"). Sequences (`core/email_sequences/`) remain manual-enrol-only here; the future `tasks/workflows/` track absorbs them.
- **External event sources** (Zapier-style ingestion). We listen to **our own** domain events only — no external webhook event sources at v1.
- **A/B testing of triggers**. Defer.

## Dependency on template-library

This track **requires** `tasks/template-library/` to be fully shipped first. Triggers reference templates via `template_id → tbl_message_templates(id)`. Without the central library:
- Triggers couldn't target email + WhatsApp from the same registry.
- Seeded default triggers (User Welcome / Lead Confirmation) would have no templates to point at.

## Multi-tenancy

Every new table — `tbl_automation_triggers`, `tbl_automation_runs`, `tbl_automation_suppressions`, `tbl_email_bounce_events` — has `org_id` UUID FK to `tbl_organizations` and Postgres RLS from its migration. Events carry `org_id` in their payload; a `lead.created` in Org A never fires Org B's triggers. Seeded default triggers are inserted per-org at org creation (not global), so each org owns + can edit its own copies. Frequency caps and quiet hours are per-org settings.

## Theme groupings

| Theme | Steps | Why grouped |
|---|---|---|
| Engine foundation | 1-4 | Event bus, trigger registry, dispatcher, scheduling — the runtime |
| Default triggers from existing modules | 5-6 | User welcome + lead confirmation (the manager's two specific asks) |
| Frontend | 7-9 | Automations list, trigger editor, run history |
| Fan-out triggers | 10-12 | Appointments, quotes/invoices, birthday/stale-lead |
| Send-time enforcement | 13 | Frequency cap + quiet hours + DPDP suppression |
| Deliverability | 14 | Bounce/complaint webhook handlers + DKIM/SPF status surface |

After Step 6, the "welcome on signup" and "confirm on lead-created" promises are kept end-to-end. Steps 7+ add operator-visible UI and depth.

## Steps index

| # | Title | Status | Effort |
|---|---|---|---|
| 1 | [Event bus + automation schema](step-1-event-bus-and-schema.md) | **Pending** | ~1 day |
| 2 | [Trigger service + condition evaluator](step-2-trigger-service-and-conditions.md) | **Pending** | ~1 day |
| 3 | [Trigger router + permissions](step-3-trigger-router-and-permissions.md) | **Pending** | ~0.5 days |
| 4 | [Dispatcher + Celery scheduling](step-4-dispatcher-and-celery-scheduling.md) | **Pending** | ~1 day |
| 5 | [user.signed_up event + Welcome trigger seed](step-5-user-signed-up-trigger.md) | **Pending** | ~0.5 days |
| 6 | [lead.created from everywhere + Lead Confirmation seed](step-6-lead-created-trigger-everywhere.md) | **Pending** | ~1.5 days |
| 7 | [Automations list UI](step-7-automations-list-ui.md) | **Pending** | ~1 day |
| 8 | [Trigger editor UI](step-8-trigger-editor-ui.md) | **Pending** | ~1.5 days |
| 9 | [Run history UI + per-contact timeline](step-9-run-history-ui.md) | **Pending** | ~1 day |
| 10 | [Appointment triggers (booked + reminders)](step-10-appointment-triggers.md) | **Pending** | ~1 day |
| 11 | [Quote + invoice triggers](step-11-quote-and-invoice-triggers.md) | **Pending** | ~1 day |
| 12 | [Time-based triggers (birthday, stale-lead)](step-12-time-based-triggers.md) | **Pending** | ~1 day |
| 13 | [Frequency cap + quiet hours + DPDP suppression](step-13-frequency-cap-and-quiet-hours.md) | **Pending** | ~1 day |
| 14 | [Bounce/complaint webhooks + DKIM/SPF surface](step-14-deliverability-and-bounces.md) | **Pending** | ~1.5 days |

**Total: 14 steps, ~13 days.**

## UI surfaces touched

| Page | What changes | In which step |
|---|---|---|
| Sidebar | New top-level "Automations" entry under Settings group (Owner + Admin visible) | Step 7 |
| Automations list (NEW) | List of triggers with enable/disable toggle + "Last fired" + "Runs in last 7d" + clone + delete | Step 7 |
| Trigger editor (NEW) | Event picker + condition builder + channel + template picker (deep-link to Templates module) + delay + recipient resolver | Step 8 |
| Trigger run history (NEW) | Per-trigger run table with status + payload + error + retry button | Step 9 |
| Contact detail page | New "Automations" tab — what triggers fired for this contact, what they got, did it deliver/open/click | Step 9 |
| Settings → General | Org-level quiet-hours + frequency-cap controls + DPDP marketing-consent policy | Step 13 |
| Settings → Email | DKIM / SPF / DMARC status badges per sender domain + suppression list viewer | Step 14 |
| Settings → Roles | Three new permission keys (`automations.read / write / runs.read`) registered | Step 3 |

## Convention — data-access layer (track-wide)

Every backend step in this track follows the project's data-access convention (`feedback_data_access_naming.md`, manager spec 2026-06-23):

- **New SQL / ORM queries go into `core/automation/data_access/<entity>.py`** — not inline in `service.py` / `dispatcher.py` / `tasks.py` / `scheduler.py`.
- The `data_access/` folder is a **leaf** — never imports a `service.py`. Sub-files split by entity (triggers, runs, suppressions, bounce_events) and `__init__.py` re-exports.
- **Reads** belong in the DAL. **Writes** + Celery side-effects + audit emits stay in `service.py` / `dispatcher.py` / `tasks.py`.
- Step 1 creates `core/automation/data_access/` with `triggers.py` + `runs.py` from day one.
- Cross-module reads (e.g. the send-guard's `tbl_contacts.whatsapp_opt_in_status` check, or the dispatcher's `tbl_message_templates` lookup for the template body) call into the OWNING module's `data_access/` (`core/contacts/data_access/`, `core/templates/data_access/`). Never duplicate the query in our DAL.

The same convention is followed in `tasks/template-library/` (the predecessor track).

## The 10 rules — track-wide notes

- **Rule 1** (core never imports packs): Automation engine is pure `core/`. No furniture pack hooks. ✓
- **Rule 2** (org_id + RLS): every new table — `tbl_automation_triggers`, `_runs`, `_suppressions`, `tbl_email_bounce_events` — has `org_id` FK + RLS policy from its first migration. ✓
- **Rule 3** (custom fields): N/A — triggers don't expose custom fields.
- **Rule 4** (dynamic forms): N/A — trigger editor is static.
- **Rule 5** (sidebar registry): new "Automations" entry registered via `module.py` in Step 7.
- **Rule 6** (permission registry): three new permission keys registered in Step 3.
- **Rule 7** (pack.yaml): no furniture defaults change. ✓
- **Rule 8** (step size): every step ≤ ~10 files / ~400 lines, individually shippable.
- **Rule 9** (no skipping verification): stop-report after each step.
- **Rule 10** (no TODOs): every step leaves the codebase clean and runnable.
