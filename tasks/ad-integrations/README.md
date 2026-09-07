# Ad Integrations (Google Ads + Meta Ads)

OAuth + webhook receivers that pipe leads from Google Ads Lead Form Extensions and Meta Lead Ads (Facebook + Instagram are both Meta) directly into the CRM with `source='google_ads'` or `'meta_ads'`. Owner connects each provider once per org via OAuth, picks which campaigns/forms feed which CRM, and configures field mappings; from then on every ad-submitted lead arrives in seconds, deduplicated against existing contacts and routed to the team.

## Why this exists

Paid ads are how Indian furniture retailers acquire most net-new customers — Meta dominates for in-store traffic, Google for high-intent search. Today, ad-form leads land in Meta's "Leads Center" or in a CSV that nobody downloads in time. By the time the sales rep sees the lead, the customer has moved on. Reducing that time-to-contact from days to seconds is the single highest-leverage feature in the entire CRM for this segment.

Per the manager spec (2026-05-22): integrate Google Ads and Meta Ads (which covers both Facebook and Instagram).

| Gap | What's missing today |
|---|---|
| **No OAuth client** | We have no Google or Meta OAuth client registered, no per-org token storage, no token refresh loop. |
| **No webhook receivers** | Meta uses a webhook subscription model; Google uses a webhook URL configured per Lead Form. Neither endpoint exists. |
| **No field-mapping per integration** | Ad-form fields ("FULL_NAME", "WORK_EMAIL", "VEHICLE_INTEREST") don't match our schema. Need per-integration mapping config, just like bulk-import. |
| **No per-org campaign/form linkage** | An org with 5 ad accounts and 30 forms across them needs UI to pick which forms feed the CRM. |
| **No dedup across sources** | Without cross-source dedup, a single buyer who clicks both a Google ad and a Meta ad creates two leads. |
| **No retry/dead-letter** | A webhook delivery that fails (CRM transient error) is dropped by the ad platform after a few retries. We need our own retry queue + DLQ for replay. |
| **No abuse/auth verification** | Both providers sign webhook payloads. We must verify the signature; an unverified webhook is a wide-open lead-injection vector. |

## What this does NOT do

- **Does not handle Google Ads conversion tracking** (the offline-conversion-upload flow). Lead receipt only.
- **Does not sync back to the ad platform.** One-way: their forms → our CRM. We do not push lead status back to Meta/Google.
- **Does not integrate with TikTok, LinkedIn, Snapchat, or any other ad platform.** Two providers only for v1.
- **Does not handle Meta WhatsApp message ads** — those flow into the conversations module (separate Phase 3 work).
- **Does not include attribution beyond what the platform tells us** — `utm_*` from the ad payload is captured into `leads.attribution` (same column added in the embeddable-widget track), nothing more.
- **Does not auto-create campaigns** in our CRM (campaigns module is its own surface in Phase 3.15/3.16). The integration just stamps `source` and stores raw `external_campaign_id` / `external_form_id` for cross-reference.
- **Does not touch `features/admin/`.**

## Acceptance criteria

A new Owner, on a fresh org, can:

1. Navigate to `/user/settings/integrations` → see two cards: "Google Ads" and "Meta Ads", each marked "Not connected".
2. Click "Connect Google Ads" → redirected to Google OAuth consent screen → grants permission → redirected back to `/user/settings/integrations/google?status=connected`.
3. Card now shows "Connected as <google account email>", with a list of detected Google Ads accounts and per-account a list of Lead Forms. Owner ticks the forms they want to feed the CRM.
4. For each selected form, Owner can edit the field mapping (form field → CRM field), with sensible defaults pre-filled.
5. Within Google Ads UI, configure the webhook URL `https://api.furnicrm.app/api/v1/integrations/google/webhook` with the per-org delivery key shown in our Settings page.
6. Submit a test lead through the Google Ads Lead Form preview tool → within a few seconds, a new lead appears in `/user/leads` with the amber "Google Ads" badge, mapped fields populated, and `attribution.external_form_id` set.
7. Repeat 2–6 for Meta Ads, picking the Facebook Page + lead-ad campaigns to subscribe to. After the OAuth grant, Meta subscription is set up by our backend automatically (Meta's API allows programmatic subscription, unlike Google).
8. Connect a second Meta account to a second org → leads from each org are isolated; RLS works.
9. As Employee → Settings → Integrations is hidden.
10. Disconnect Google → tokens revoked + webhook receiver returns 410 for that org's webhook key until re-connected.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend: `integrations` table + token storage (encrypted at rest)](step-1-backend-integrations-table.md) | Done | ~1 day |
| — | [Manual: Google Ads OAuth setup + verification](manual-google-oauth-setup.md) | DevOps — kick off NOW | 2-6 wk external |
| — | [Manual: Meta Ads OAuth setup + verification](manual-meta-oauth-setup.md) | DevOps — kick off NOW | 1-3 wk external |
| 2 | [Backend: Google Ads OAuth flow](step-2-backend-google-oauth.md) | Pending | ~1 day |
| 3 | [Backend: Google Ads webhook receiver + signature verification + retry queue](step-3-backend-google-webhook.md) | Pending | ~1 day |
| 4 | [Backend: Meta OAuth flow + auto-subscription](step-4-backend-meta-oauth-and-subscription.md) | Pending | ~1 day |
| 5 | [Backend: Meta Lead Ads webhook receiver + signature verification](step-5-backend-meta-webhook.md) | Pending | ~1 day |
| 6 | [Backend: cross-source dedup + lead routing (round-robin / by-store)](step-6-backend-dedup-and-routing.md) | Pending | ~1 day |
| 7 | [Frontend (Settings): Integrations page — connect/disconnect + form/campaign picker](step-7-frontend-settings-integrations-page.md) | Pending | ~1 day |
| 8 | [Frontend: per-integration field mapping editor + integration status dashboard](step-8-frontend-mapping-editor-and-status.md) | Pending | ~1 day |
| 9 | [Frontend: Meta card per-form Attach + Edit-Mapping (parity with Google card)](step-9-frontend-meta-card-per-form-mapping.md) | Done | ~0.5 day |
| 10 | [Backend: per-form pipeline_stage on subscriptions](step-10-backend-per-form-pipeline-stage.md) | Done (migration awaits upgrade) | ~0.5 day |
| 11 | [Backend: Google worker parity for pipeline_stage](step-11-backend-google-worker-pipeline-parity.md) | Done | ~0.1 day |
| 12 | [Frontend: Pipeline Stage dropdown in the mapping editor](step-12-frontend-mapping-editor-pipeline-stage.md) | Done | ~0.5 day |
| 13 | [Backend: auto-attach every Lead Form when a Page is subscribed](step-13-backend-auto-attach-forms-on-page-subscribe.md) | Done | ~0.3 day |

**Total: ~8 working days.** This is the most external-dependency-heavy track in the project; expect overruns from OAuth app review processes on both Google and Meta sides (typically 1–2 weeks of back-and-forth before scopes are approved for production traffic). The code is ready in 8 days; production go-live waits on OAuth app review.

## Dependencies

- Manual Lead Entry Step 1 (`lead.source` enum includes `google_ads` and `meta_ads`) — required.
- Embeddable Widget Step 2 (`leads.attribution` JSONB column) — required; this track writes to the same column.
- Bulk Import Step 3 (mapping registry + targets) — reused for per-integration field mapping.
- Phase 1.5 (permissions, audit, org settings) — required.
- Phase 1.7 (audit log) — every OAuth grant/revoke + every webhook delivery emits audit events.
- Phase 2.4 / 2.11 (Contacts + Leads backend) — webhook handlers create both via the same services manual entry uses.
- Celery + Redis (locked stack) — Step 3/5 retry queue runs as Celery tasks.

## File budget

| Area | Files |
|---|---|
| Backend Step 1 | 1 migration + 4 new (`core/integrations/{models,schemas,service,crypto}.py`) + 1 modified (`permissions/registry.py`) + 1 test |
| Backend Step 2 | 4 new (`core/integrations/google/{oauth,api_client,sync_forms}.py` + `core/integrations/google/__init__.py`) + 1 modified router + 1 test |
| Backend Step 3 | 3 new (`core/integrations/google/webhook.py` + `core/integrations/google/tasks.py` + `core/integrations/google/dlq.py`) + 1 modified router + 1 test |
| Backend Step 4 | 4 new (`core/integrations/meta/{oauth,api_client,subscriptions}.py` + `__init__.py`) + 1 modified router + 1 test |
| Backend Step 5 | 2 new (`core/integrations/meta/webhook.py` + `core/integrations/meta/tasks.py`) + 1 modified router + 1 test |
| Backend Step 6 | 1 new (`core/leads/dedup.py` extended) + 1 new (`core/leads/routing.py`) + 1 migration (add `assigned_to` if not present) + 2 tests |
| Frontend Step 7 | 3 new (`integrations-page.component.ts/.html` + `integrations-api.service.ts`) + 2 new (provider cards `google-card.component.ts/.html`, `meta-card.component.ts/.html`) + 1 modified settings routes |
| Frontend Step 8 | 3 new (`field-mapping-editor.component.ts/.html` + `integration-status.component.ts`) + 1 modified `integrations-api.service.ts` |

**Total ~40 files across 8 steps.** Largest single step (Step 2) ships 6 files. Inside rule-8 budget per step.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| OAuth tokens are encrypted at rest | Step 1 — `crypto.py` uses Fernet symmetric encryption with a key from `settings.INTEGRATIONS_ENCRYPTION_KEY`; tokens decrypted only in the worker process that needs them. |
| Webhook payloads verified before processing | Steps 3 + 5 — each provider's signature scheme implemented and tested. Unverified payloads return 401 + audit event `integration.webhook.invalid_signature`. |
| Every webhook delivery enqueues to Celery, never blocks the receiver | Steps 3 + 5 — receiver only validates signature and enqueues; the lead-creation work runs async with retry policy. |
| DLQ for permanently failed webhooks | Step 3 — `dlq.py` records payloads that exhausted retries; Settings UI exposes them for manual replay. |
| Leads carry `source='google_ads' \| 'meta_ads'`, `actor_user_id=NULL`, `attribution.external_*` populated | Step 6 — single ingestion path; cannot be bypassed. |
| Cross-source dedup on (phone, email) | Step 6 — extends `dedup.py` from the bulk-import track; ad leads are dedup'd against existing leads in the same org. |
| Lead routing assigns `assigned_to` deterministically | Step 6 — round-robin by default; per-org rules editable in Settings (future task — for v1, just round-robin). |
| OAuth app secrets never in code | All in `.env` via `pydantic-settings`. |
| `org_id` on every new table | `integrations`, `integration_subscriptions`, `integration_dlq` all carry it; RLS attached. |
| Audit events on connect/disconnect/delivery | `integration.connected`, `integration.disconnected`, `integration.webhook.received`, `integration.webhook.invalid_signature`, `integration.webhook.dlq`. |

## Self-check against the 10 rules

- Rule 1: Pure core. No pack import.
- Rule 2: All new tables have `org_id` + RLS.
- Rule 3: Custom fields layer unaffected.
- Rule 4: Field mapping editor renders dynamically from the targets endpoint (shared with bulk-import).
- Rule 5: Settings → Integrations registers via the existing settings-tab registry.
- Rule 6: One new permission key `settings.integrations.manage` (covers both providers).
- Rule 7: `pack.yaml` unaffected. Pack may later contribute platform-specific default mappings (e.g. furniture-specific interest categories on Meta forms), composable.
- Rule 8: 40 files across 8 steps; largest step has 6 files. Tight but inside.
- Rule 9: Stop-and-report after each step.
- Rule 10: No TODOs. OAuth flows ship complete; DLQ replay UI ships in Step 7/8.

## Operational concerns

- **OAuth app review:** Google requires a verified domain + privacy policy + scopes justification; Meta requires App Review for production access to lead-retrieval scopes. **This is an external blocker** — typically 1–2 weeks. Start the application processes in parallel with Steps 1/2/4 so review and code converge.
- **Webhook URL stability:** the production webhook URL must be stable across deploys. Hardcode in env, version in path: `/api/v1/integrations/google/webhook/v1`.
- **Test environments:** both Google and Meta have test/sandbox modes (Google: test accounts in OAuth client config; Meta: Test Users in app dashboard). Use these for Steps 3 + 5 tests, never real ad campaigns.
- **Rate limits:** both providers cap webhook delivery rate. We are the consumer; their caps don't affect us. But our Celery retry policy must not hammer our own backend.

## After this track

- Every Google Ads + Meta Ads lead arrives in seconds, fully attributed, assigned to a rep.
- The four-channel lead-ingestion ambition (manual + bulk + widget + ads) is complete. Every realistic lead source feeds the same kanban.
- The integrations table + OAuth + webhook patterns become the template for future provider integrations (TikTok ads, LinkedIn ads, Tally form, JotForm, Typeform) — none of which are in scope here but all of which can follow the same shape.
