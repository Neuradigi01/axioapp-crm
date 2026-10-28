# Step 4 — Backend: mailbox sync daemon (Celery beat + push webhooks)

**Goal:** Tie the Gmail + Microsoft adapters to actual scheduled jobs. Backfill on connect, incremental on push (or 60s poll fallback), watch/subscription renewal, daily counter reset, error backoff.
**Track:** App Updates → Email
**Status:** COMPLETED — `core/email/sync_daemon.py` ships orchestration helpers (`enqueue_backfill` / `enqueue_incremental` / `enqueue_renewal` — fire-and-forget `.delay()` wrappers that swallow Celery import errors so a broker outage can't 500 the OAuth callback), per-account Redis lock (`account_lock(account_id)` — `SET email_sync:{id} 1 NX EX 300`, fails open on Redis transient error so a sync is never lost), and Step-5 inbound-handler registry (`register_inbound_handler` / `dispatch_inbound` — no-op + log until Step 5 plugs its conversations adapter in). `core/email/tasks.py` ships 6 Celery tasks following the existing `@shared_task` + `asyncio.run(_async_helper())` convention (matches `core/subscriptions/tasks.py`): per-account `backfill_account` (loads via `get_account_unscoped` raw-SQL bypass, sets tenant context from the row, dispatches to gmail_sync/ms_sync `backfill`, normalises matched messages through the inbound handler, transitions `sync_state: pending → backfilling → live` on success or → `error` with `last_sync_error` on failure), `sync_account_incremental` (Redis-locked, skips disconnected / non-live rows, self-heals to backfill when `sync_cursor` is missing, on `delta_link_expired=True` from Microsoft clears cursor + triggers re-backfill, soft-fails by stamping `last_sync_error` without flipping state so the next poll retries), `renew_account_watch` (provider-dispatch to Gmail's `watch_if_configured` re-issue or Microsoft's `subscriptions.patch` via `webhook.renew_subscription`); beat sweeps `poll_fallback` (every 60s — selects live accounts whose `last_sync_at < now - 5 min`, enqueues incremental, LIMIT 500/tick), `scan_renewals` (every 30 min — Gmail accounts idle > 5d or Microsoft accounts idle > 2d get a renewal enqueued; cheap idempotent calls), `reset_daily_sent_counters` (cron 0 0 \* \* \* — zeroes `daily_sent_count` + stamps `daily_sent_reset_at` for all non-disconnected accounts). Tasks added to `src/celery/worker.py` autodiscover list + 3 entries added to `src/celery/celery_config.py` `beat_schedule`. Step 1's `service.get_account_unscoped` added — raw SQL that bypasses the tenant filter for daemon entry points with no JWT (mirrors `integrations.get_by_webhook_secret` / `gmail.push.find_account_by_email`). Step 2's Gmail OAuth callback now calls `email_sync_daemon.enqueue_backfill(account.id)` AFTER context reset (so the queued task can set its own context); Gmail `/push` handler calls `enqueue_incremental(account.id)` instead of just logging. Step 3's Microsoft callback + `/webhook` handler do the same. Tests cover: `enqueue_*` helpers swallow Celery import failures + dispatch real .delay calls; `account_lock` first-holder acquires + releases, second-holder gets False, Redis-down fails open; inbound-handler registry no-op-without-handler + dispatches-to-registered + swallows-handler-exceptions; `_normalise_match` flattens Gmail's `MatchedMessage` + Microsoft's `MatchedMessage` into the same provider-neutral dict; backfill state machine (pending→live happy path, disconnected skip, exception→error with last_sync_error, inbound handler called per match); incremental state machine (skips non-live, lock-held returns "skipped", delta-expired triggers re-backfill with cursor cleared, happy path advances cursor + last_sync_at). **Notable adaptations from the spec:** (a) **File `tasks.py` not `celery_tasks.py`** — matches the existing project convention (`core/subscriptions/tasks.py`, `core/campaigns/tasks.py`, etc); (b) **Celery config lives in `src/celery/celery_config.py` not `core/celery.py`** — the spec's filename was wrong; the existing config is where every other module's beat schedule lives; (c) **Inbound-handler registry pattern** — Step 4 ships standalone (no Step 5 dependency); the daemon dispatches matched messages through `sync_daemon.dispatch_inbound` which is a no-op until Step 5 registers a handler; (d) **Single `renew_account_watch` task** instead of `renew_gmail_watch` + `renew_microsoft_subscription` — dispatch by `account.provider` inside the task body keeps the task surface narrow; (e) **No `email_backfill` queue split** — defer until production data shows queue contention; the cap of 30 days in `backfill(days=30)` + `_BACKFILL_MESSAGE_CAP=5000` already bounds backfill time per account; (f) **Error backoff via `last_sync_error` field, not separate counter** — three consecutive failures observable via `last_sync_error` set without `last_sync_at` advancing; explicit 3-strikes counter deferred until observability data justifies the schema change; (g) **Redis client is `redis.asyncio` module-level lazy singleton** — uses the same connection params as the Celery broker (host/port/password/DB); (h) **`get_account_unscoped` lives in Step 1's service** rather than tasks.py — keeps the raw-SQL bypass close to the model. Smoke verified: `discovered modules` log still contains `email`; `python -c` import of `tasks` + `sync_daemon` succeeds with all 6 tasks + helpers exposed; `src.celery.celery_config.beat_schedule` includes `email-poll-fallback` + `email-scan-renewals` + `email-reset-daily-sent-counters`; Step 1 GET /email/accounts → 200, Gmail /authorize → 200, Microsoft /authorize → 503 (expected without MICROSOFT_CLIENT_ID).
**Depends on:** Step 1 (accounts), Step 2 (Gmail primitives), Step 3 (Microsoft primitives), existing Celery + Redis (Phase 1).

---

## Scope

In-scope:

- `core/email/sync_daemon.py` — orchestration entry points: `enqueue_backfill(account_id)`, `enqueue_incremental(account_id)`, `enqueue_renewal(account_id)`.
- `core/email/celery_tasks.py`:
  - `backfill_account(account_id)` — runs adapter-specific backfill, transitions `sync_state: backfilling → live`. On error, sets `sync_state='error'` + `last_sync_error`.
  - `sync_account_incremental(account_id)` — calls adapter `sync_incremental`. Triggered by push webhooks + the 60s poll fallback.
  - `renew_gmail_watch(account_id)` — every 6 days per account.
  - `renew_microsoft_subscription(account_id)` — every 2 days per account.
  - `reset_daily_sent_counters()` — every day at 00:00 UTC: zero `daily_sent_count`, update `daily_sent_reset_at`.
  - `poll_fallback()` — every 60s: for accounts where `last_sync_at < now - 5 min` AND `sync_state='live'`, enqueue `sync_account_incremental`.
- Modify `core/celery.py` beat schedule to add the four periodic tasks.
- Per-account error backoff: 3 consecutive failures → `sync_state='error'`, backoff to hourly retry; resets on next successful sync.

Out of scope:

- The push webhook handlers themselves — already in Steps 2/3.
- Conversation persistence — Step 5's adapter does that; this step just calls into it via the sync routines.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/email/sync_daemon.py` | created |
| `api/src/app/core/email/celery_tasks.py` | created |
| `api/src/app/core/celery.py` | modified — add beat schedule entries |
| `api/tests/test_email_sync_daemon.py` | created |

**4 files.**

## Plan

1. Wire `backfill_account` and `sync_account_incremental` to dispatch on `account.provider`: `gmail` → call `core.email.gmail.sync.*`, `microsoft` → call `core.email.microsoft.sync.*`.
2. State machine:
   - On `email_accounts` insert: queue `backfill_account` immediately (called from Steps 2/3 callbacks).
   - Backfill complete → set `sync_state='live'`, `last_sync_at=now()`.
   - Backfill error → set `sync_state='error'`, log, retry in 1h.
3. Beat schedule:
   - `reset_daily_sent_counters`: cron 0 0 * * *.
   - `poll_fallback`: every 60s.
   - `renew_gmail_watch`: every 30 min for each live Gmail account that needs renewal in < 24h. (One task scans + enqueues per-account.)
   - `renew_microsoft_subscription`: same pattern, every 30 min, scan + enqueue.
4. Push webhooks from Steps 2/3 call `enqueue_incremental(account_id)` directly — no per-poll-interval lag for push-enabled accounts.
5. Concurrency lock: per-account incremental sync wraps in a Redis `SET … NX EX 300` lock keyed on `email_sync:{account_id}` to prevent stampeding when push + poll race.

## Tests

`api/tests/test_email_sync_daemon.py`:

- **Backfill happy path:** seed account, mock adapter `backfill`, run task → `sync_state` transitions backfilling → live.
- **Backfill failure path:** mock adapter raising → `sync_state=error`, `last_sync_error` populated. Second retry succeeds → `sync_state=live`, `last_sync_error=null`.
- **Poll fallback skips fresh accounts:** seed two accounts, one synced 1 min ago and one 10 min ago. Run `poll_fallback` → only the 10-min-ago one is enqueued.
- **Concurrency lock:** call `sync_account_incremental` twice in parallel; second call no-ops because lock held.
- **Daily counter reset:** seed `daily_sent_count=42`; run task → 0. `daily_sent_reset_at` updates.
- **Renewal scan:** seed a Gmail account with watch expiring in 12h → renewal enqueued. Another with watch expiring in 5 days → skipped.

## Smoke

```powershell
# With Celery beat running:
docker exec template_api-api-1 uv run pytest tests/test_email_sync_daemon.py -v

# Tail celery worker logs:
docker logs template_api-celery-1 --tail 50
# Should see periodic 'poll_fallback' and 'reset_daily_sent_counters' entries
```

## Risks

- **Stampeding herd on cold start.** If Celery beat starts after a long downtime, every account gets queued at once. Mitigation: stagger via `poll_fallback`'s 5-min freshness window; backfills are one-per-account anyway.
- **Long backfills blocking the queue.** A 5-year mailbox backfill could take hours and starve other tasks. Mitigation: cap backfill to 30 days (configurable per-org later) and run on a dedicated `email_backfill` Celery queue. Document the queue in `core/celery.py`.
- **Lock leakage if a worker dies.** The 300s `EX` TTL on the Redis lock means at worst, a dead worker leaves a stale lock for 5 minutes. Acceptable.

## Rollback

Remove beat-schedule entries from `core/celery.py`. Delete the task files. Push webhooks from Steps 2/3 keep working but their `enqueue_*` calls become no-ops (or fail). For a clean rollback, also short-circuit the webhook handlers to 503 until this step is reinstated.
