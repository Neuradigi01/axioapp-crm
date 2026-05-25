# Step 9 — Frontend (Settings): submission log + abuse signals

**Goal:** Add a "Submission log" sub-tab inside the Embed Integrations Settings page showing the last 30 days of submission attempts (accepted, spam-rejected, rate-limited) with timestamps, source URLs, hashed IPs, and outcome breakdowns. Gives Owner/Admin operational visibility — "is anyone using my embed?" and "are bots hitting me?"
**Track:** Embeddable Widget
**Status:** Done — `embed_submissions` table + `embed_submission_outcome` Postgres enum (`accepted | rejected_spam | rate_limited | invalid_payload`; **`invalid_key` deliberately excluded** because those rows have no org context and would violate RLS — they stay in the audit log only) added via migration 0047 with `apply_rls` + two composite indexes (`(org_id, created_at DESC)` for the list hot path, `(org_id, outcome, created_at DESC)` for filtered queries + the summary's per-outcome group-by). Migration uses a `DO $$ ... EXCEPTION WHEN duplicate_object ...` block + `PgEnum(create_type=False)` so it's idempotent across aborted-then-retried runs (the dev DB had a stray enum leftover). SQLAlchemy model is `EmbedSubmissionLog` (named `…Log` to avoid shadowing the existing Pydantic `EmbedSubmission` request body), enum is `EmbedSubmissionOutcome`. New `log_service.py` ships `hash_ip` (privacy-preserving 16-hex SHA-256 prefix, returns `None` for missing/unknown), `record(...)` (best-effort write, opens its own tenant-scoped session, never raises), `list_rows(...)` (paginated + outcome filter + range filter), `summary(...)` (per-outcome totals + per-day stacked buckets with zero-fill so the chart x-axis is dense), and `purge_old_embed_submissions()` (cross-tenant cleanup beyond 30-day retention, wired into `tasks_collections.run_every_day`). `submissions.py` pipeline now records a row at every termination point: `accepted` (post-lead-creation, with `lead_id`), `rejected_spam` (honeypot/min_time/recaptcha_invalid/recaptcha_low_score — both audit event + log row via the new `_record_spam_reject` helper), `rate_limited` (reason `per_key` or `per_ip`), `invalid_payload` (caught HTTPException, logged with truncated detail, then re-raised). Two new admin endpoints behind `settings.integrations.embed.manage`: `GET /embed/submissions?outcome=&from=&to=&page=&page_size=` (returns `EmbedSubmissionListResponse` with `{items, total, page, page_size}`) and `GET /embed/submissions/summary?from=&to=` (returns `EmbedSubmissionSummary` with `by_outcome` totals + per-day `EmbedSubmissionDayBucket[]`; defaults to last 30 days). Frontend: `embed-api.service.ts` typed with `EmbedSubmissionRead` + envelope + filter/range/summary shapes; new `SubmissionLogComponent` (standalone, OnPush, signals) renders a 4-cell counts card (Accepted/Spam/Rate-limited/Errors over last 30 days), a stacked Chart.js bar chart (per-day, 4 series, last 30 days regardless of table filter — consistent trend visibility), and a paginated table with `outcomeOptions` + `rangeOptions` chip filters (24h/7d/30d), outcome badges, host-extracted source link, hashed IP column, "View lead" router link for accepted rows, prev/next pagination footer with totals, empty state. `EmbedIntegrationsTabComponent` now has an `activeTab` signal switching between "Keys & configuration" (the original Step 4–8 panels) and "Submission log" (the new component) via a minimal `border-b-2` tab strip. 34/34 backend tests green in 8.68s (24 existing Step 8 + 10 new: 4 hash_ip + 6 submit-writes-log integration). Angular `tsc --noEmit` clean + dev build succeeds (12.18s, no template errors).
**Depends on:** Steps 1–8 (all backend events + UI scaffolding).

---

## Scope

In-scope:

- **Backend (small):**
  - `embed_submissions` table — one row per submission attempt (accepted or rejected), with `org_id`, `key_id`, `created_at`, `ip_hash`, `referrer`, `landing_url`, `outcome` enum (`accepted | rejected_spam | rate_limited | invalid_payload | invalid_key`), `lead_id` (nullable), `reason` (free text for spam/error subtype).
  - The submission service from Steps 2/8 writes a row at the end of each request (accepted or otherwise).
  - 30-day TTL: a Celery beat task `purge_old_embed_submissions` runs daily, deletes rows older than 30 days. Configurable retention later.
  - Admin endpoint `GET /api/v1/embed/submissions?from=&to=&outcome=&page=&page_size=`.
  - Admin endpoint `GET /api/v1/embed/submissions/summary?from=&to=` returning counts by outcome and a per-day series (for the small chart).

- **Frontend:**
  - New sub-tab "Submission log" inside `EmbedIntegrationsTabComponent` (use a tab strip within the page, not a separate Settings tab).
  - Top: a summary card with counts for the last 7 days: `Accepted | Spam | Rate-limited | Errors`.
  - Below: a small bar chart (per-day counts, last 30 days) — use the existing chart library in the app (likely Chart.js or ngx-charts; mirror whatever is used in the dashboard).
  - Below: a paginated table of recent submissions with columns: time, outcome badge, source URL (clickable, truncated to host), referrer, IP hash, lead link (if accepted).
  - Filter strip: outcome dropdown, time range presets (24h / 7d / 30d).
  - Empty state when no submissions exist yet.

Out of scope:

- No alerting on abuse spikes — log only.
- No PII unmasking (IP last-octet hashing is intentional).
- No export to CSV — possible follow-on.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_embed_submissions.py` | created |
| `api/src/app/core/embed/models.py` | modified — `EmbedSubmission`, `EmbedSubmissionOutcome` enum |
| `api/src/app/core/embed/schemas.py` | modified — `EmbedSubmissionRead`, `EmbedSubmissionSummary` |
| `api/src/app/core/embed/submissions.py` | modified — record row at end of every code path |
| `api/src/app/core/embed/router.py` | modified — `GET /embed/submissions`, `GET /embed/submissions/summary` |
| `api/src/app/core/embed/tasks.py` | created — Celery beat `purge_old_embed_submissions` |
| `api/tests/test_embed_submission_log.py` | created |
| `app/src/app/features/user/core/settings/integrations/embed/submission-log.component.ts` | created |
| `app/src/app/features/user/core/settings/integrations/embed/submission-log.component.html` | created |
| `app/src/app/features/user/core/settings/integrations/embed/embed-integrations-tab.component.ts` | modified (small) — wire the tab strip |
| `app/src/app/features/user/core/settings/integrations/embed/embed-api.service.ts` | modified (small) — `listSubmissions(filters)`, `getSubmissionSummary(range)` |

**11 files, 1 migration.** Marginally over rule-8 ceiling. Split into 9a (backend) and 9b (frontend) at implementation time if the diff feels heavy.

## Plan

1. Migration: `embed_submissions` table with `org_id`, `key_id` FK (nullable — `invalid_key` outcome has no key), `outcome` enum, `created_at`, `ip_hash`, `referrer`, `landing_url`, `lead_id` FK (nullable), `reason` (text, nullable). RLS by `org_id`. Index on `(org_id, created_at DESC)` and `(org_id, outcome, created_at DESC)`.
2. Extend `submissions.submit()` and the rate-limit branch in the router to write an `EmbedSubmission` row at the end of every request. For `invalid_key`, set `key_id=NULL` and `org_id=NULL` — but we need `org_id` for RLS; this row is special. Solution: `invalid_key` rows go to a separate, system-owned table OR are simply dropped (we already audit them). **Decision: drop `invalid_key` from the log** — they're audit-only. The submissions log shows only events with a known key (and thus a known org).
3. Implement Celery beat task `purge_old_embed_submissions` — `DELETE FROM embed_submissions WHERE created_at < now() - interval '30 days'`. Wired into `celery_beat_schedule` in `app/shared/celery.py`.
4. Implement admin endpoints. Pagination + outcome filter. Summary endpoint returns `{by_outcome: {...}, by_day: [{date, accepted, spam, rate_limited, errors}, ...]}`.
5. Build `SubmissionLogComponent`. Three sections:
   - Summary card (counts).
   - Bar chart (per-day stacked by outcome).
   - Paginated table with filters.
6. Wire the tab strip in `EmbedIntegrationsTabComponent` so users can switch between "Keys & Config" and "Submission Log" without leaving the page.
7. Tests.

## Tests

`api/tests/test_embed_submission_log.py`:

- **Row written on accept:** POST a valid submission → exactly one row in `embed_submissions` with `outcome='accepted'` and `lead_id` set.
- **Row written on spam:** honeypot filled → row with `outcome='rejected_spam'`, `reason='honeypot'`, `lead_id=NULL`.
- **Row written on rate-limited:** 21st burst submission → row with `outcome='rate_limited'`.
- **No row on invalid_key:** decision documented above; assert.
- **GET endpoint paginates + filters:** seed 50 rows mixed outcomes; list with `outcome=accepted&page_size=10` returns 10 accepted only.
- **Summary endpoint:** seed varied rows across 7 days; assert `by_outcome` totals match and `by_day` array has 7 entries with correct buckets.
- **RLS:** Org A's submissions are not visible to Org B.
- **Purge task:** seed a row dated 31 days ago + a row dated yesterday; run the task; assert only the recent one remains.

## Smoke (browser)

```
1. Submit several leads via the widget (some good, some honeypot-filled, some rapid).
2. Settings → Integrations → Embed widget → switch to "Submission log" tab.
3. Summary card shows the counts. Chart shows the per-day bars (last 30 days).
4. Table shows rows: most recent submission at top with outcome badge, referrer,
   IP hash, "View lead" link for accepted ones.
5. Filter outcome to "Spam". Table narrows to honeypot/rate-limit rejects.
6. Click "View lead" on an accepted row → navigates to /user/leads/<id>.
7. As Employee → tab hidden; direct URL → Access Denied.
```

## Risks

- **High write volume on the hot path:** every submission writes 2 rows (the lead row + the submission row). Acceptable at 100 req/hr/key. If load grows, batch writes via a buffer or move the submission log to a separate write path.
- **`embed_submissions` table growth:** 30-day retention caps it. A busy widget at 1k submissions/day = 30k rows max — trivial.
- **Bar chart vs. line chart:** stacked bars are visually denser but read better at low counts. Use Chart.js stacked-bar; mirror the dashboard's style.
- **`ip_hash` collision:** `sha256(ip)[:16]` has ~64 bits; for a per-org 30-day window, collision risk is negligible. Good enough for "group by IP".

## Rollback

Reverse migration. Delete the new files. Revert the writes in `submissions.py`. Settings tab strip reverts to single panel.
