# App Updates

Two large feature tracks that close the biggest "this isn't a complete CRM" gaps surfaced in the 2026-06-11 audit. Both are platform features that every adopter benefits from regardless of vertical — they belong in `core/`, not in the furniture pack.

## Why this folder exists

The audit found the CRM is ~85% complete as a furniture-vertical product but only ~60% complete as a general-purpose CRM template. The two load-bearing gaps versus a standard CRM (HubSpot / Zoho / Salesforce) are:

| Gap | Status today | Track |
|---|---|---|
| **Email** — no inbox sync, no templates, no sequences. Channel enum exists; no adapter. | 0% built | [`email/`](email/README.md) |
| **Reporting & dashboards** — only workload summary. No funnel, no conversion %, no sales-by-rep, no forecasting. | ~10% built | [`reporting/`](reporting/README.md) |

These two tracks supersede the thin placeholders in `phase-5-core-crm-launch/step-5.5-reporting.md` (which becomes a pointer to this folder) and a brand-new email track that didn't exist in the original plan.

## Tracks

| # | Track | Steps | Effort | Status |
|---|---|---|---|---|
| 1 | [Email — inbox sync, templates, sequences](email/README.md) | 11 | ~18 working days | Pending |
| 2 | [Reporting — funnel, sales-by-rep, forecasting, dashboards](reporting/README.md) | 8 | ~10 working days | Pending |

## Sequencing recommendation

Reporting first. Reasons:
1. **Faster wins.** Reporting is ~10 days and doesn't depend on third-party OAuth approval cycles. Email is ~18 days plus 1–4 weeks waiting on Gmail OAuth verification + Microsoft Graph review.
2. **Unblocks dashboards.** Step 5.1 (Admin Dashboard) in Phase 5 depends on having real metric endpoints — reporting delivers those.
3. **Demoable.** Funnel + sales-by-rep charts are the single most asked-for screenshot by prospects. Email value is invisible until a real account is connected.

Email second, kicked off in parallel on the DevOps side (Gmail + Microsoft OAuth app verification can start the day this track is approved — those clocks run independently of code).

## Relationship to the rest of the plan

- **Phase 5.5 (Reporting)** — the thin one-pager is superseded by this folder. Mark it Done-by-redirect when the reporting sub-track lands.
- **Phase 5.1 (Admin Dashboard)** — depends on Reporting Step 6 (widget library) and Step 8 (dashboard integration). Push 5.1 to after reporting lands.
- **Phase 3 conversations / channels** — the email track plugs an Email channel adapter into the existing conversations module. No new top-level inbox is introduced; everything flows through `core/conversations/`.
- **Phase 5.2 (AI Chatbot)** — once email is live, the AI follow-up work in Phase 5.3 has a real send-channel to wire into. Email is a prerequisite for AI follow-ups being useful.

## Cross-track invariants

These apply to both sub-tracks:

| Rule | Applied |
|---|---|
| Every new table has `org_id` + RLS | Yes — `email_accounts`, `email_messages`, `email_templates`, `email_sequences`, `report_snapshots`, etc. all carry `org_id`. |
| `core/` never imports `packs/` | Yes — both tracks are pure core. |
| Custom fields layered model | Email templates accept `{{contact.custom_data.foo}}` variables via the same JSONB column. Reports filter by custom fields via the same schema. |
| Dynamic forms | Template editor and sequence builder both render from field-definition endpoints. |
| Module registry | New `email`, `email_templates`, `email_sequences`, `reporting` modules each ship a `module.py` and register their permission keys. |
| Permissions registry | New keys: `email.read`, `email.send`, `email.accounts.manage`, `email.templates.manage`, `email.sequences.manage`, `reports.read`, `reports.export`. |
| No TODOs / no "I'll fix it later" | Yes. |

## File budget

| Track | Files | Migrations |
|---|---|---|
| Email | ~75 files across 11 steps | 6 migrations |
| Reporting | ~40 files across 8 steps | 1 migration (snapshots only) |

Each step ≤ ~10 files per Rule 8.

## Status maintenance

Per saved feedback: when a step lands, flip `**Status:** Pending` → `**Status:** COMPLETED` inside the step's MD file **and** update the step-table row in this folder's track README. The parent `tasks/README.md` index also gets a pointer to `app-updates/` so the global progress map stays accurate.
