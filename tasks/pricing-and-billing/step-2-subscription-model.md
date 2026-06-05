# Step 2 — Subscription model + migration

**Goal:** Add a `subscriptions` table that stores exactly one active subscription per organization, with the columns needed for tier / status / trial timing / seat count / billing cycle / Stripe linkage — and backfill existing seeded orgs to a sensible default.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Step 1 (plan registry — `plan_code` foreign-key-like reference points to YAML codes). Phase 1.4 (multi-tenancy: `organizations` table must exist with `id UUID PK`).

---

## Scope

One new table, one Alembic migration, one SQLAlchemy model, and the supporting Pydantic schemas. **No HTTP endpoints in this step** — read/write APIs land in Steps 7/8/9. This step just exists to put the row in place so subsequent steps have something to read from.

## Schema

### New table: `subscriptions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `uuid_generate_v4()` |
| `org_id` | UUID FK → `organizations.id` | NOT NULL, indexed, RLS scope |
| `plan_code` | TEXT NOT NULL | references a code in `plans.yaml` (no FK because plans live in YAML); CHECK constraint validates against known codes at app layer in Step 3 |
| `status` | TEXT NOT NULL | enum-like: `trialing`, `active`, `past_due`, `read_only`, `archived`, `cancelled` |
| `billing_cycle` | TEXT NOT NULL | `monthly` or `annual`. Default `monthly`. Trial = `monthly` (irrelevant but non-null) |
| `seats_purchased` | INTEGER NOT NULL | minimum = plan's `included_seats`; can grow with overage |
| `trial_started_at` | TIMESTAMPTZ NULL | set on trial creation; null for plans that didn't start as trials |
| `trial_ends_at` | TIMESTAMPTZ NULL | `trial_started_at + 14 days` |
| `current_period_start` | TIMESTAMPTZ NOT NULL | renewal cycle anchor |
| `current_period_end` | TIMESTAMPTZ NOT NULL | next billing date |
| `read_only_at` | TIMESTAMPTZ NULL | set when status transitions to `read_only` |
| `archived_at` | TIMESTAMPTZ NULL | set when status transitions to `archived` |
| `cancelled_at` | TIMESTAMPTZ NULL | set on explicit cancellation |
| `stripe_customer_id` | TEXT NULL | populated in Step 11+ when Stripe is wired |
| `stripe_subscription_id` | TEXT NULL | populated when a paid subscription is created in Stripe |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | trigger or app-side bump |

### Indexes / constraints

| Constraint | Purpose |
|---|---|
| `subscriptions_org_id_idx` | every read filters by `org_id` |
| Partial unique: `(org_id) WHERE status IN ('trialing','active','past_due','read_only')` | invariant: one active sub per org. `archived` and `cancelled` rows are history and can stack. |
| `subscriptions_status_check` | CHECK constraint enforcing valid status values |
| `subscriptions_billing_cycle_check` | CHECK constraint enforcing `monthly` or `annual` |
| RLS policy `subscriptions_org_isolation` | `USING (org_id = current_setting('app.current_org_id')::uuid)` per Rule 2 |

### Backfill

Existing orgs (seeded, demo, etc.) get a single row inserted with:
- `plan_code = 'trial'`
- `status = 'trialing'`
- `trial_started_at = now()` (giving them a fresh 14-day clock starting from migration date — non-destructive)
- `trial_ends_at = now() + interval '14 days'`
- `seats_purchased = 3`
- `current_period_start = now()`
- `current_period_end = now() + interval '14 days'`

This is a pragmatic decision: rather than picking an arbitrary paid plan for existing orgs (which would imply we charged them), treat the migration as the start of their trial. The smoke target org (Ajay's Workspace per ops memory) gets this same treatment.

### Migration file

`api/alembic/versions/00XX_subscriptions_table.py`:

- `op.create_table('subscriptions', ...)` with all columns above
- `op.create_index(...)` for `org_id`
- `op.execute(...)` to add the partial unique index (Alembic shortcut doesn't support partials; use raw SQL)
- `op.execute(...)` to add the CHECK constraints
- RLS policy as raw SQL (`CREATE POLICY ... USING ...`)
- Backfill: `op.execute(INSERT INTO subscriptions ... SELECT id FROM organizations ...)`
- `downgrade()` drops the table cleanly (RLS policy drops with the table)

## Backend

### New SQLAlchemy model

`api/src/app/core/billing/models.py`:

```python
class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    plan_code: Mapped[str]
    status: Mapped[str]
    billing_cycle: Mapped[str]
    seats_purchased: Mapped[int]

    trial_started_at: Mapped[datetime | None]
    trial_ends_at: Mapped[datetime | None]
    current_period_start: Mapped[datetime]
    current_period_end: Mapped[datetime]
    read_only_at: Mapped[datetime | None]
    archived_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]

    stripe_customer_id: Mapped[str | None]
    stripe_subscription_id: Mapped[str | None]

    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

SQLAlchemy 2.x async style, `Mapped` annotations, no v1 patterns.

### Pydantic schemas

`api/src/app/core/billing/schemas.py`:

- `SubscriptionRead` — full read shape (status, trial dates, seats, period)
- `SubscriptionStatus` — Literal enum
- `BillingCycle` — Literal enum

### Service skeleton

`api/src/app/core/billing/service.py`:

- `get_active_subscription(session, org_id) -> Subscription | None` — looks up the row where status is not in `('archived','cancelled')`.

No write functions yet — they land in Step 6 (create on signup) and Steps 8–9 (change plan / seats).

## Frontend

Out of scope. The billing settings page in Step 16 will read via the API in Step 7.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_subscriptions_table.py` | created |
| `api/src/app/core/billing/models.py` | created |
| `api/src/app/core/billing/schemas.py` | created — `SubscriptionRead`, status / cycle literals |
| `api/src/app/core/billing/service.py` | created — `get_active_subscription` only |
| `api/src/app/shared/db.py` (or equivalent) | modified — register new model in metadata if needed |
| `api/tests/core/billing/test_subscriptions_schema.py` | created |

**6 files + 1 migration.** Within rule.

## Tests

`api/tests/core/billing/test_subscriptions_schema.py`:

- **Migration creates table:** `upgrade()` then `SELECT * FROM subscriptions` works; columns and types match spec.
- **Backfill landed:** count of `subscriptions` rows equals count of `organizations` rows; every row is `status = 'trialing'`, `plan_code = 'trial'`, `trial_ends_at` is ~14 days in future.
- **Unique-active invariant holds:** inserting a second `status='trialing'` row for the same `org_id` raises an `IntegrityError`. Inserting a second `status='archived'` row succeeds (history allowed).
- **Status CHECK:** inserting `status='gibberish'` raises.
- **Billing cycle CHECK:** inserting `billing_cycle='quarterly'` raises.
- **RLS isolation:** session set to org A cannot select rows belonging to org B.
- **`get_active_subscription`:** returns the trialing row for an org with one trialing sub; returns `None` for an org with only archived subs.
- **Downgrade clean:** `downgrade()` drops the table without errors.

## Smoke

```
# Backup DB before migration test (optional but recommended).
.\API\docker-helper.cmd migrate    # apply 00XX
docker exec template_api-api-1 pytest tests/core/billing/test_subscriptions_schema.py -v

# Manual DB check inside container:
.\API\docker-helper.cmd shell-db
SELECT id, plan_code, status, trial_ends_at FROM subscriptions LIMIT 5;
# → 1 row per existing org, all trialing, all ~14 days in future.

# Downgrade test:
.\API\docker-helper.cmd downgrade -1
SELECT * FROM subscriptions;   # → relation does not exist (table dropped)
.\API\docker-helper.cmd migrate
```

(DB ops go through `docker-helper.cmd` per ops memory — `.env` password is encrypted; host-side `uv run alembic` will not connect.)

## Risks

- **Backfill gives existing orgs a fresh 14-day clock starting at migration time.** If the smoke org is in active use, the team needs to know they're now "on trial" until day 15. Communicate before running in production. For local dev, this is fine.
- **The partial unique index is a Postgres-only construct.** Cannot be expressed as a SQLAlchemy `UniqueConstraint`. Use `op.execute("CREATE UNIQUE INDEX ...")` in the migration. Document in the model docstring.
- **`stripe_customer_id` / `stripe_subscription_id` nullable.** They stay null for the entire trial period and only populate after Step 13's webhook handler creates them. Consumers must tolerate null.
- **`plan_code` is not a FK** because plans live in YAML. Step 3's entitlement service validates the code on every read; an unknown code raises. Plans should be removed from YAML only after no active subs reference them.

## Rollback

Revert the 6 source files + downgrade the migration. The downgrade drops the table cleanly. No external state to undo (no Stripe rows created yet — Step 13 is when that risk appears).
