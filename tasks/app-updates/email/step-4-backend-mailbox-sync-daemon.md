# Step 4 — Backend: mailbox sync daemon (Celery beat + push webhooks)

**Goal:** Tie the Gmail + Microsoft adapters to actual scheduled jobs. Backfill on connect, incremental on push (or 60s poll fallback), watch/subscription renewal, daily counter reset, error backoff.
**Track:** App Updates → Email
**Status:** Pending
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
