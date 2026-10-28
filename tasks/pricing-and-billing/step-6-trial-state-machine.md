# Step 6 — Trial state machine + signup hook

**Goal:** On every new org creation (via the self-signup flow from the RBAC-Ownership track Step 1), insert a `subscriptions` row with `status='trialing'`, `plan_code='trial'`, `trial_ends_at = now() + 14 days`. Run a Celery task that advances the state machine: `trialing → read_only → archived → deleted` on the schedule defined in the README.
**Track:** Pricing and Billing
**Status:** COMPLETED — migration `0076_subs_reminders_sent` applied (one column added: `subscriptions.reminders_sent JSONB NOT NULL DEFAULT '{}'::jsonb`, backfill verified on 16 existing rows). `signup_hook.create_trial_subscription` wired into BOTH register handlers (`register_with_new_org` and `register_user_only` in `core/auth/service.py`) so every fresh signup gets a 14-day trial inside the same atomic transaction as the org / Owner / OrganizationMember inserts — a later failure rolls the trial back too. `lifecycle.py` ships `transition_if_due` (race-safe conditional `UPDATE ... WHERE id=? AND status=<expected>` so a concurrent paid upgrade aborts cleanly), `scan_and_transition_due` (returns counted summary), `fire_due_reminders` (3-day `trial_ending_soon` dedup via `reminders_sent['trial_ending_soon']` JSONB key, mark-first-send-after so a crash produces silence not duplicates), `_delete_archived` (drops the row at archived + 90d, emits `org.deleted`). System actor convention: `user_id=None` on `audit.log` calls — matches the existing nullable `audit_logs.user_id` column. Email side effects route through `notifications.py` stub that logs `billing_email.queued`; Step 20 swaps the real SMTP impl in. Celery `advance_trial_lifecycle` task runs hourly at minute=10 (offset from period-rollover at :05 and lead-score at :00). Open decisions resolved: 3-day reminder dedup → JSONB column (simpler than separate table for the tiny taxonomy); system actor → `user_id=None`. Path divergence: `core/subscriptions/` not `core/billing/` (Step 1 reason). 18 tests written but **not run** per the user's batch-tests instruction.
**Depends on:** Step 2 (subscription model), Step 5 (period rollover infrastructure), RBAC-Ownership Step 1 (new-org-on-signup hook). Phase 1.7 (audit logs) — required for emitting `subscription.created`, `trial.expired` events.

---

## Scope

Three things:

1. A **signup hook** that creates a trial subscription whenever a new org is created via the normal-signup path. Wired into the transactional handler from RBAC-Ownership Step 1.
2. A **state-machine service** with a single function `transition(subscription) -> new_status` that computes the correct next state based on current status + timestamps.
3. A **Celery task** running every hour that scans for subscriptions whose deadline has passed and applies the transition.

Plus tests for each.

## State machine

```
                           ┌──────────────────┐
   signup                  │     trialing     │
  ────────────────────────►│ trial_ends_at +0 │
                           └──────┬───────────┘
                                  │ day 15
                                  ▼
                           ┌──────────────────┐
                           │    read_only     │
                           │  read_only_at +0 │
                           └──────┬───────────┘
                                  │ +30 days
                                  ▼
                           ┌──────────────────┐
                           │     archived     │
                           │  archived_at +0  │
                           └──────┬───────────┘
                                  │ +90 days
                                  ▼
                            (record deleted;
                             org marked deleted_at,
                             data export window closes)

   payment success (any non-deleted state) ──► active
   plan change while trialing ──► active (or stays trialing if changing within trial)
```

| From | Condition | To | Side effects |
|---|---|---|---|
| `trialing` | `now() > trial_ends_at` | `read_only` | set `read_only_at = now()`; emit audit `trial.expired`; emit email `trial_expired` (Step 20) |
| `read_only` | `now() > read_only_at + 30 days` | `archived` | set `archived_at = now()`; emit audit `subscription.archived`; emit email `subscription_archived` |
| `archived` | `now() > archived_at + 90 days` | _row deleted; org soft-deleted_ | emit audit `org.deleted`; data preserved per export-window contract (Phase 5 GDPR step) |
| `trialing` / `read_only` | payment success | `active` | set `plan_code` to chosen tier; clear `read_only_at`; set new `current_period_start/end` based on cycle; emit audit `subscription.created` (first paid period) |
| any non-deleted | `cancellation API hit` | `cancelled` (terminal) | set `cancelled_at`; behaves as `archived` for read/write rules |

## Signup hook

`api/src/app/core/billing/signup_hook.py`:

```python
async def create_trial_subscription(session, org_id: UUID) -> Subscription:
    """
    Called inside the new-org transaction from RBAC-Ownership Step 1's register handler.
    Inserts the trial subscription. Does NOT commit — the parent transaction commits.
    """
    sub = Subscription(
        org_id=org_id,
        plan_code="trial",
        status="trialing",
        billing_cycle="monthly",
        seats_purchased=3,
        trial_started_at=now(),
        trial_ends_at=now() + timedelta(days=14),
        current_period_start=now(),
        current_period_end=now() + timedelta(days=14),
    )
    session.add(sub)
    return sub
```

The register handler in RBAC-Ownership Step 1 calls this **between** "insert organization" and "commit." Failure here rolls back the whole signup transaction (org + Owner + roles + sub) — no orphaned orgs without subscriptions.

## State machine service

`api/src/app/core/billing/lifecycle.py`:

```python
async def transition_if_due(session, subscription: Subscription) -> str | None:
    """
    Checks the current status + timestamps against now(). If a transition is due,
    applies it (updates row, emits audit + email events). Returns the new status,
    or None if no transition.
    """

async def scan_and_transition_due(session) -> dict:
    """
    Scans all non-terminal subscriptions, calls transition_if_due on each.
    Returns a summary dict: {trialing_to_read_only: N, read_only_to_archived: N, ...}.
    Called by the Celery task below.
    """
```

The function is idempotent: calling it twice on a subscription that's already transitioned is a no-op.

## Celery task

`api/src/app/core/billing/tasks.py` (extended from Step 5):

```python
@celery_app.task
def advance_trial_lifecycle():
    """
    Runs hourly. Scans subscriptions for due transitions and applies them.
    Logs the summary.
    """
```

Celery Beat schedule: every hour at minute 5 (offset from the period-rollover task at minute 0 to avoid contention).

## Audit + email side effects

This step **emits the events** (writes to `audit_logs`, queues outbound email tasks) but **does not deliver the emails** themselves — email templates and SMTP wiring land in Step 20. The lifecycle service calls into a stub `notifications.send_billing_email(...)` that Step 20 implements.

Events emitted:

| Trigger | Audit event | Email |
|---|---|---|
| Trial → read_only | `trial.expired` | `trial_expired` to Owner |
| Read_only → archived | `subscription.archived` | `subscription_archived` to Owner |
| Archived → deleted | `org.deleted` | (no email — already churned) |
| 3 days before trial_ends_at | (none) | `trial_ending_soon` to Owner |

The "3 days before" reminder needs its own scheduled scan inside `advance_trial_lifecycle` — it does not transition state but does fire the email.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/signup_hook.py` | created — `create_trial_subscription` |
| `api/src/app/core/billing/lifecycle.py` | created — `transition_if_due`, `scan_and_transition_due` |
| `api/src/app/core/billing/tasks.py` | modified (from Step 5) — add `advance_trial_lifecycle` task |
| `api/src/app/shared/celery_app.py` | modified — register beat schedule for the new task |
| `api/src/app/core/auth/service.py` | modified — call `create_trial_subscription` inside the existing register transaction (RBAC-Ownership Step 1's handler) |
| `api/src/app/core/notifications/stubs.py` | created — `send_billing_email` stub used by lifecycle; Step 20 replaces with real implementation |
| `api/tests/core/billing/test_trial_lifecycle.py` | created |

**7 files.** Within rule.

## Tests

`test_trial_lifecycle.py`:

- **Signup creates trial subscription:** new register call → assert subscription row with `status='trialing'`, `trial_ends_at` ≈ now + 14d.
- **Signup rollback on subscription failure:** monkey-patch `create_trial_subscription` to raise → assert NO org, user, or role rows landed (transaction held).
- **Trial → read_only at deadline:** fixture sub with `trial_ends_at = now() - 1 hour`; run `transition_if_due` → status becomes `read_only`, `read_only_at` set.
- **Read_only → archived at deadline:** fixture sub with `read_only_at = now() - 31 days`; run → `archived`.
- **Archived → deleted at deadline:** fixture sub with `archived_at = now() - 91 days`; run → row deleted, audit `org.deleted` emitted.
- **Idempotent:** call `transition_if_due` twice on a just-transitioned sub → second call returns None, no extra audit events.
- **`scan_and_transition_due` batches correctly:** seed 5 trials at various stages, run scan, assert exactly the due ones transitioned and the summary dict is accurate.
- **3-day reminder fires once:** sub with `trial_ends_at = now() + 2 days`; run scan; assert `trial_ending_soon` email queued; run again same day; assert NOT re-queued (dedup via `reminders_sent` JSONB column on subscription, or a separate `subscription_reminders` table — TBD at step kickoff).
- **Audit events written:** every transition writes a row to `audit_logs` with the right event name, actor=`system`, org_id set.

## Smoke

```
.\API\docker-helper.cmd migrate    # if a reminders dedup column is added
docker exec template_api-api-1 pytest tests/core/billing/test_trial_lifecycle.py -v

# End-to-end signup smoke (needs RBAC-Ownership Step 1 landed):
# 1. Open /accounts/register, complete signup
# 2. .\API\docker-helper.cmd shell-db
#    SELECT plan_code, status, trial_ends_at FROM subscriptions WHERE org_id = '<new org id>';
#    → trial, trialing, now()+14d

# Force advance:
docker exec -it template_api-api-1 uv run python -c "
import asyncio
from app.core.billing.lifecycle import scan_and_transition_due
from app.shared.db import async_session
async def go():
    async with async_session() as s:
        # First mutate trial_ends_at backward via raw SQL, then scan
        await s.execute('UPDATE subscriptions SET trial_ends_at = now() - interval \\'1 hour\\' WHERE org_id = ...')
        print(await scan_and_transition_due(s))
asyncio.run(go())
"
# → {'trialing_to_read_only': 1, ...}

# Verify status flipped:
SELECT status, read_only_at FROM subscriptions WHERE org_id = ...;
```

## Risks

- **3-day reminder dedup.** Simplest implementation: add a `reminders_sent JSONB DEFAULT '{}'` column to `subscriptions`, set `reminders_sent['trial_ending_soon'] = true` when sent. Or: a separate `subscription_reminders(subscription_id, kind, sent_at)` table. Resolve at step kickoff; either is fine but pick one and commit.
- **Hourly task lag means status updates can be up to 60 minutes late.** Acceptable for trial expiry (the user sees a write fail in the meantime, which they treat as "trial just ended" — close enough). For tight SLAs, switch to every-15-minutes.
- **System actor in audit_logs.** Audit infra (Phase 1.7) expects an `actor_user_id`. Lifecycle transitions have no user actor. Use a sentinel UUID or a dedicated `actor_kind='system'` column — defer to Phase 1.7's schema. Document the convention used.
- **Race between paid upgrade and trial expiry.** If a user pays at minute 59 but the hourly scan runs at minute 5, the user might briefly see "read-only" mode. Mitigation: the `transition_if_due` function checks the current status — if it changed to `active` between rows-read and rows-write, the transition aborts. Implement with `UPDATE ... WHERE status = 'trialing'` (atomic conditional update).

## Rollback

Revert the 7 source files. The signup hook reverts cleanly (orgs created after revert no longer get auto-subscriptions — they'd appear as "unmetered" until Step 6 re-lands). The Celery task revert means transitions stop happening; existing rows remain in their last state. No data loss.
