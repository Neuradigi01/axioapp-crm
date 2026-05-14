# Step DR.4 — Move demo logins from hardcoded array to DB

**Goal:** Eliminate the `DEMO_PRESETS` constant in `login.component.ts` by sourcing the test-login list from the database. Production builds end up with zero demo credentials baked in; dev/staging surfaces the list via a dev-only endpoint.
**Phase:** 4.5 — Demo Roles Setup (side task)
**Depends on:** DR.1, DR.2 (and ideally DR.3 verified)
**Status:** Parked (not started)

## Why this exists

DR.2 shipped a working dropdown but with the 4 presets hardcoded inside the Angular component:

```ts
const DEMO_PRESETS: readonly DemoPreset[] = [
  { label: 'Core CRM — Admin', identifier: 'admin@core-demo.local', password: 'Admin@123', ... },
  ...
];
```

That's three smells in one:

1. **Plain-text passwords in source code** — even demo passwords ship to production unless the bundle strips them.
2. **Two sources of truth** — if a seed script renames a user, the dropdown silently breaks.
3. **Customer / QA can't add their own test logins** without editing TypeScript.

DR.4 fixes all three by moving the list to the DB.

## Scope

**In-scope:**
- Add `is_demo BOOLEAN NOT NULL DEFAULT FALSE` column on `users`. (Migration.)
- Add new table `demo_credentials(user_id PK FK→users.id, plain_password TEXT NOT NULL, created_at)`. (Migration.) This table NEVER goes to production — its migration is gated behind an env flag (`SEED_DEMO_DATA=true`), or it's a separate "dev-overlay" migration set that prod doesn't apply.
- Update `seed_core_demo_org.py` to flip `is_demo=True` on the 3 new users AND insert matching rows in `demo_credentials`.
- Add a one-off back-fill SQL / mini-script to mark the existing `admin@demo.local` user as `is_demo=True` and seed its credential row.
- Add a dev-only router `api/src/app/core/dev/router.py` with `GET /api/v1/_dev/demo-logins` that returns `[{label, email, org_slug, password}]` joining `users` (where `is_demo=True`) with `demo_credentials` and `organizations` for slug/name. Router mounts in `main.py` only when `os.getenv("ENABLE_DEV_ENDPOINTS") == "true"`.
- Refactor `login.component.ts`:
  - Remove the hardcoded `DEMO_PRESETS` constant.
  - Inject an HTTP client + the new endpoint URL.
  - Fetch on `ngOnInit`. If the endpoint returns 404 (not mounted) or empty array → dropdown auto-hides.

**Out of scope:**
- Touching production migration set (so prod schema never gets `demo_credentials` table).
- Adding a UI to manage demo logins (just read-only fetch is enough).

## Files to touch

- `api/alembic/versions/0029_users_is_demo.py` (created — adds `users.is_demo` column)
- `api/alembic/versions/0030_demo_credentials.py` (created — gated dev-only table)
- `api/src/app/core/dev/__init__.py` + `router.py` (created)
- `api/src/app/core/users/models.py` (modified — adds `is_demo` Mapped column)
- `api/src/app/main.py` (modified — conditionally mounts dev router)
- `api/src/app/scripts/seed_core_demo_org.py` (modified — sets is_demo + writes demo_credentials)
- `api/src/app/scripts/seed_admin_user.py` (modified — same for `admin@demo.local`)
- `app/src/app/features/accounts/login/login.component.ts` (modified — fetch instead of hardcoded)

## Plan

1. **Migrations.** Two of them. `0029` is a column add (safe for prod). `0030` is the credentials table — keep it in a separate migration file so it can be conditionally applied in dev/staging only.
2. **Model.** Add `is_demo: Mapped[bool]` on `User`.
3. **Dev router.** New file. One endpoint, env-gated mount.
4. **Seeds.** Update both seed scripts to write `is_demo=True` + `demo_credentials` row.
5. **Frontend.** Replace the const with a `signal<DemoPreset[]>([])` + `HttpClient.get(...)` in `ngOnInit`. Add a `loadFailedSilently` flag — production hits 404, swallow, dropdown stays hidden.

## DB changes / migrations

- ALTER TABLE users ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT FALSE
- CREATE TABLE demo_credentials (user_id UUID PK FK→users.id ON DELETE CASCADE, plain_password TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now())
- No RLS on `demo_credentials` — it's a global dev-only lookup table; the row IS the secret.

## Tests to add

- `tests/test_dev_demo_logins.py` — verifies the endpoint returns the expected shape, returns empty when `ENABLE_DEV_ENDPOINTS` is unset, returns 404 when the router isn't mounted.

## Verification checklist

**Backend:**
- `.\docker-helper.cmd upgrade` applies both migrations cleanly.
- Re-run `seed_core_demo_org` → users now flagged `is_demo=True`, credentials rows present.
- `curl /api/v1/_dev/demo-logins` with `ENABLE_DEV_ENDPOINTS=true` → returns the 4-entry array.
- Same curl with the env unset → 404.

**Frontend:**
- `ng build` clean. No TS errors.
- Page-load on `/accounts/login`: dropdown populated via the API, identical UX to DR.2.
- If the endpoint 404s (e.g. point Angular at a prod-like backend), dropdown is hidden, login form still works.

**Code review:**
- Confirm `DEMO_PRESETS` constant is fully removed from the component.
- Confirm no hardcoded `Admin@123` strings remain in `app/src/...`.

## Self-check (10 rules)

- [ ] Rule 2 — `demo_credentials.user_id` FKs back into a `users` row that already carries `org_id`; access only via that join.
- [ ] Rule 8 — ~8 files, well under 400 lines.
- [ ] Rule 10 — no TODOs; the env-gated mount is the production-safe pattern, not a "fix later" workaround.

## Stop & report

Demo the dropdown still works (visually identical to DR.2) but now sourced from the DB. Then resume Phase 5.
