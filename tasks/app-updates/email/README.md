# Email — Inbox sync, templates, sequences

Per-user OAuth-connected mailboxes (Gmail + Microsoft 365) that two-way sync into the CRM's conversations module under the existing `email` channel. Sales reps compose, send, and reply to email from inside the CRM. Email templates and multi-step sequences (drip campaigns) let teams automate outreach at scale. Open/click tracking gives marketing real attribution.

## Why this exists

The 2026-06-11 audit named email as the single biggest gap versus a standard CRM. Every CRM buyer compares on email first — "can my reps work their day from inside this tool?" — and today the answer is no. Conversations module has an `email` channel enum (Phase 3.8) but no adapter behind it. Reps still bounce between Gmail/Outlook and the CRM, copy-pasting context, losing history, and forgetting to log activities.

The vertical is furniture retail in India where >70% of B2C leads still come through phone + WhatsApp, but B2B (interior designers, builders, hospitality buyers) is overwhelmingly email-led. Every B2B-leaning store this product targets will reject a CRM without email.

| Gap | What's missing today |
|---|---|
| **No OAuth client for Gmail/Microsoft** | No Google OAuth scopes for Gmail API, no Microsoft Graph app registration, no per-user token storage. |
| **No mailbox sync** | No daemon polling IMAP/Graph, no historical backfill, no incremental sync via Gmail's `historyId` / Graph's `deltaToken`. |
| **No send pipeline** | Conversations module's compose bar (Phase 3.10) has an Email channel adapter stub that returns 501. |
| **No templates** | No CRUD for email templates, no variable substitution, no inline images, no per-org library. |
| **No sequences / cadences** | No multi-step outreach automation. Today the only "sequence" is a one-shot campaign blast in Phase 3.15. |
| **No tracking** | No open pixel, no link rewriter, no per-send delivery state machine beyond what the campaigns module already does for bulk. |
| **No deliverability hygiene** | No SPF/DKIM check, no bounce handling, no unsubscribe footer enforcement, no list-unsubscribe header. |
| **No threading** | Replies from the customer don't land back on the originating activity — they create a new conversation. |

## What this does NOT do

- **Does not build a competitor to Gmail.** No full inbox UI — the CRM only surfaces emails that touch a known contact or lead. Personal inbox stays in Gmail.
- **Does not handle calendar.** Calendar sync is a separate (smaller) track if and when prospects ask. Appointments module already covers internal scheduling.
- **Does not handle email signatures with rich HTML editor.** Plain HTML signatures only for v1 — the WYSIWYG editor is post-v1.
- **Does not handle SMTP relay sending.** Outbound goes through the user's connected Gmail/Microsoft account — we are not a sender of record. (Bulk campaigns from Phase 3.15 continue to use the existing transactional ESP path; this track is for 1:1 + sequenced 1:many, not 1:N blast.)
- **Does not integrate with IMAP-only providers** (Yahoo, Zoho Mail, custom domains). v1 = Gmail + Microsoft 365 only. IMAP/SMTP fallback is a v2 consideration.
- **Does not handle attachments larger than 25 MB.** Both providers cap there anyway.
- **Does not touch `features/admin/`.**

## Acceptance criteria

A sales rep on a fresh org can:

1. Navigate to `/user/settings/email-accounts` → click "Connect Gmail" → OAuth consent → redirected back with the account showing as Connected.
2. Within ~60 seconds, the last 30 days of their inbox/sent items that touched a known CRM contact appear under that contact's Activities timeline as `kind=email` rows.
3. Open any contact → click "Compose Email" → pick a template ("Initial outreach — designer") → variables resolve from contact fields → send. Email actually arrives in the customer's inbox, sent from the rep's own Gmail. Activity logs in CRM with `direction=outbound`, `delivered_at` timestamp.
4. Customer replies. Within 60 seconds the reply appears in the same Conversations thread + as a new Activity on the contact + as an in-app notification to the rep.
5. Settings → Templates → create a new template with variables `{{contact.first_name}}` and `{{lead.pipeline_stage}}`. Use it from compose. Variables render.
6. Settings → Sequences → create a 3-step sequence: Day 0 send Template A, Day 2 if no reply send Template B, Day 5 if no reply send Template C. Enroll 12 leads. Watch the kanban: at the relevant days, the right emails fire, and any reply auto-pauses the sequence for that lead.
7. Open a sent email's activity row → see "Opened 3× • Last opened 2h ago • Link clicked: /products/sofa-amaya" badges.
8. As Owner → Settings → Email → see a per-account "Last sync" + "Daily send count" dashboard. Disconnect a rep's account → all sync stops; sent history retained.
9. RLS: A second org connecting a different Gmail account does not see Org A's messages, templates, or sequences. Permission gate: a Junior Sales Executive without `email.templates.manage` can use templates but not create them.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend: `email_accounts` table + OAuth foundation (shared)](step-1-backend-email-accounts-and-oauth.md) | COMPLETED | ~1 day |
| 2 | [Backend: Gmail adapter (OAuth + history-based sync + send)](step-2-backend-gmail-adapter.md) | COMPLETED | ~2 days |
| 3 | [Backend: Microsoft Graph adapter (OAuth + delta sync + send)](step-3-backend-outlook-adapter.md) | COMPLETED | ~2 days |
| 4 | [Backend: mailbox sync daemon (Celery beat + push webhooks)](step-4-backend-mailbox-sync-daemon.md) | COMPLETED | ~1 day |
| 5 | [Backend: Conversations Email channel adapter (compose + reply threading)](step-5-backend-conversations-email-adapter.md) | COMPLETED | ~1 day |
| 6 | [Backend: `email_templates` table + variable substitution engine](step-6-backend-email-templates.md) | COMPLETED | ~1 day |
| 7 | [Backend: `email_sequences` + enrollment engine + reply detection](step-7-backend-email-sequences.md) | COMPLETED | ~2 days |
| 8 | [Backend: open pixel + link rewriting + delivery state](step-8-backend-open-click-tracking.md) | COMPLETED | ~1 day |
| 9 | [Frontend (Settings): Email Accounts tab — connect/disconnect + per-account dashboard](step-9-frontend-email-accounts-tab.md) | Pending | ~1 day |
| 10 | [Frontend: Template editor (Settings) + compose-from-template in contacts/leads](step-10-frontend-template-editor.md) | Pending | ~1.5 days |
| 11 | [Frontend: Sequence builder + enrollment UI from leads/contacts list](step-11-frontend-sequence-builder.md) | Pending | ~2 days |

**Total: ~15.5 working days.** Add 1–4 weeks of external OAuth verification clock on top — both Gmail (Google OAuth verification for `gmail.modify` scope) and Microsoft Graph (publisher verification for tenant-wide install) require app review with restricted scopes. **Kick the OAuth applications off the day this track is approved.**

## Dependencies

- Phase 1.5 (permissions, audit) — required.
- Phase 1.7 (audit log) — every account connect/disconnect, every template create, every sequence enroll/pause emits audit events.
- Phase 2.4 (Contacts backend) — sync engine matches inbound emails to contacts via the existing email column.
- Phase 2.6 (Activities timeline) — synced emails create activities with `kind='email'`.
- Phase 3.8 (Conversations channel registry) — required; this track plugs the Email adapter into the existing registry.
- Phase 3.10 (Conversations frontend) — required; reuses compose bar.
- Phase 3.15 (Campaigns) — share the unsubscribe/list-management infra (see Step 8).
- Celery + Redis (locked stack) — Step 4 sync daemon + Step 7 sequence scheduler.

## File budget

| Area | Files |
|---|---|
| Step 1 (accounts table + OAuth shared) | 1 migration + 5 new (`core/email/{models,schemas,service,oauth,crypto}.py`) + 1 modified (`permissions/registry.py`) + 1 test |
| Step 2 (Gmail) | 4 new (`core/email/gmail/{client,sync,send,push}.py` + `__init__.py`) + 1 modified router + 1 test |
| Step 3 (Microsoft Graph) | 4 new (`core/email/microsoft/{client,sync,send,webhook}.py` + `__init__.py`) + 1 modified router + 1 test |
| Step 4 (sync daemon) | 2 new (`core/email/sync_daemon.py` + `core/email/celery_tasks.py`) + 1 modified (`core/celery.py` beat schedule) + 1 test |
| Step 5 (conversations adapter) | 2 new (`core/conversations/channels/email_adapter.py` + thread-matching helpers) + 1 modified channel registry + 1 test |
| Step 6 (templates) | 1 migration + 4 new (`core/email_templates/{models,schemas,service,router,module}.py`) + 1 new (`core/email/variables.py` — substitution engine) + 1 test |
| Step 7 (sequences) | 2 migrations + 5 new (`core/email_sequences/{models,schemas,service,router,scheduler,module}.py`) + 1 test |
| Step 8 (tracking) | 1 migration + 3 new (`core/email/tracking/{pixel,link_rewriter,router}.py`) + 1 modified (send pipeline) + 1 test |
| Step 9 (frontend accounts tab) | 4 new (settings tab `.ts/.html` + connect-flow `.ts/.html`) + 1 new `email-accounts-api.service.ts` + 1 modified settings routes |
| Step 10 (frontend templates) | 6 new (template-list `.ts/.html` + template-editor `.ts/.html` + template-picker `.ts/.html`) + 1 new `email-templates-api.service.ts` |
| Step 11 (frontend sequences) | 6 new (sequence-list `.ts/.html` + sequence-builder `.ts/.html` + enrollment-modal `.ts/.html`) + 1 new `email-sequences-api.service.ts` + 1 modified leads list (enroll bulk action) |

**Total ~75 files across 11 steps, 6 migrations.** Largest single step (Step 7 sequences) ships 9 files including 2 migrations — at rule-8 ceiling because the sequence engine is one logical unit.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| OAuth tokens encrypted at rest | Step 1 `crypto.py` — Fernet symmetric over a key from `EMAIL_TOKEN_KEY` env var. Reuses pattern from the integrations track. |
| Every send goes through the rep's own account | Step 5 adapter validates the requesting user owns a connected `email_account` row before allowing send. No "send on behalf of" without an explicit token. |
| Sync is incremental after the first backfill | Step 2/3 use Gmail `historyId` and Microsoft `deltaToken` — full re-sync only on disconnect+reconnect. |
| Sync only matches messages touching a known contact | Step 4 — `to/from/cc/bcc` email addresses are matched against `contacts.email`. Unmatched messages are dropped, never persisted. (Personal inbox stays personal.) |
| Reply detection auto-pauses sequences | Step 7 — sequence scheduler checks for inbound activity on the lead since enrollment before sending the next step. |
| List-unsubscribe header on every send | Step 8 — `List-Unsubscribe` + `List-Unsubscribe-Post` headers wired into the send pipeline. Required by Gmail for >5K/day senders. |
| Per-account daily send caps | Step 5 — soft cap 200/day/account default (configurable), hard cap 500/day. Protects rep from getting their Gmail account flagged. |
| `org_id` on every new table | Yes. |
| `core/` never imports `packs/` | This is core-only. |
| Audit events | `email.account.connected`, `email.account.disconnected`, `email.template.created`, `email.template.updated`, `email.template.deleted`, `email.sequence.created`, `email.sequence.enrolled`, `email.sequence.completed`, `email.sequence.paused_on_reply`. |

## Self-check against the 10 rules

- Rule 1: Pure core. Conversations adapter is registered via the existing channel registry; no pack-specific code paths.
- Rule 2: All new tables carry `org_id` + RLS.
- Rule 3: Email templates resolve `{{contact.custom_data.<key>}}` via the layered custom-fields model.
- Rule 4: Template editor + sequence builder forms render dynamically from the variable registry — no hardcoded variable lists.
- Rule 5: Three new sidebar entries (Email Inbox is the existing Conversations module — no new top-level), Templates + Sequences register themselves with menu positions under Settings.
- Rule 6: Six new permission keys, all registered via module sweep.
- Rule 7: `pack.yaml` unaffected. Furniture pack may later contribute starter templates (e.g. "Quote follow-up — sofa enquiry"); not blocking.
- Rule 8: 75 files across 11 steps, largest step is 9 files.
- Rule 9: Stop-and-report after each step.
- Rule 10: No TODOs. Bounce handling, unsubscribe, rate limiting all real from day one.

## Operational concerns

- **Gmail OAuth verification.** The `gmail.modify` scope is "restricted" — requires CASA (Cloud Application Security Assessment) annual audit (~$1K-$5K), homepage with privacy policy, demo video, security questionnaire. Allow 4–6 weeks. Without verification, the unverified-warning screen blocks >100 users. **Decision required:** which Google Workspace publisher account owns the OAuth app. Recommendation: the customer's existing Workspace if they have one, otherwise a CRM-owned publisher account.
- **Microsoft Graph publisher verification.** Less brutal than Google but still 2–3 weeks. Multi-tenant app needs MPN ID. Tenant admin consent UX is bumpy for non-admin reps.
- **Quota.** Gmail: 1 billion API requests/day default; not a concern. Per-mailbox 250 messages/day sending without warm-up — soft cap in Step 5 protects this. Microsoft Graph: 10,000 requests per 10 minutes per app per tenant — chunky sync of a large mailbox needs back-off (handled in Step 2/3).
- **Sandbox accounts.** Maintain at least one Gmail + one Outlook test account in a CRM-owned Workspace/tenant for CI smoke tests. Document in Step 11.
- **GDPR / DPA.** Connecting a personal Gmail account means we process the user's personal email metadata. Settings page must surface a clear consent + data-handling note linking to a real privacy policy. Tracking pixel must respect `Do-Not-Track`. Document in Step 9.

## After this track

- Sales reps run their day from inside the CRM. Email becomes a first-class activity surface alongside calls/WhatsApp.
- Marketing + sales get real attribution: which template converts, which sequence step is the killer, which reps are sending and at what cadence.
- AI follow-ups (Phase 5.3) become useful — there is a real send channel to wire into.
- Customer support becomes possible: a future tickets module can be a thin wrapper over email threading without rebuilding the inbox.
- We unlock the B2B furniture segment (designers, builders, hospitality) which is overwhelmingly email-led — the single biggest revenue unlock for this product.
