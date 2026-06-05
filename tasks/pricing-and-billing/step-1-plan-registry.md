# Step 1 — Plan registry + public `/plans` API

**Goal:** Define the four pricing tiers (Trial / Basic / Standard / Enterprise) as a YAML-backed plan registry, expose them via a public unauthenticated `GET /api/v1/plans` endpoint, and make this the single source of truth that downstream entitlement / billing code reads from.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Phase 1.2 (backend bootstrap) — needs FastAPI + Pydantic v2 + `core/` package in place. No subscription model yet (lands in Step 2).

---

## Scope

A code-defined plan registry that:

1. Reads `api/src/app/core/billing/plans.yaml` at process boot
2. Validates the YAML against a Pydantic schema (`Plan`, `PlanFeatures`, `PlanCaps`, `PlanPricing`)
3. Exposes the parsed plans via `GET /api/v1/plans` (public, no auth) — the landing page consumes this
4. Exposes a typed Python helper `plans.get(code: str) -> Plan` and `plans.all() -> list[Plan]` for downstream services
5. Includes a CLI sanity command (`uv run python -m app.core.billing.plans_cli validate`) used in CI to fail-fast on a malformed YAML

**No DB changes in this step.** Subscription table lands in Step 2.

## Why YAML and not Python constants

- Editable without code review by a non-engineer (pricing changes don't require a deploy via code path)
- Versionable as a single artifact (the file gets a `version` field; bumping it is the audit trail)
- Easily extended later for INR / per-region pricing (extra `currency` axis on `pricing`)
- Reusable by the furniture-pack — `packs/furniture/pricing.yaml` follows the same schema and composes on top

## The four plans (final values)

```yaml
version: 1
currency: USD
plans:
  - code: trial
    name: 14-day Trial
    display_order: 0
    is_public: false                 # not listed on /pricing; arrived at via signup
    trial_duration_days: 14
    pricing:
      monthly_bundle_usd: 0
      annual_bundle_usd: 0
      included_seats: 3
      extra_seat_monthly_usd: 0      # extra seats not purchasable during trial
      extra_seat_annual_usd: 0
    caps:
      contacts: 500
      leads_per_month: 50
      storage_mb: 100
      pipelines: 1
      custom_fields_per_entity: 5
      form_widgets: 0
      form_submissions_per_month: 0
      automation_runs_per_month: 0
      api_calls_per_day: 0
      branches: 1
      email_sends_per_month: 100
      sms_sends_per_month: 0
    features:                        # boolean entitlement keys (full list in plans.yaml)
      contacts.read: true
      contacts.write: true
      leads.manual_entry: true
      tasks.read: true
      tasks.write: true
      walkins.read: false
      pipelines.read: false
      automation.workflows: false
      conversations.unified_inbox: false
      integrations.whatsapp: false
      integrations.email_imap_smtp: false
      ads.google_webhook: false
      ads.meta_webhook: false
      calls.recording: false
      campaigns.email: false
      sso.saml: false
      audit.full_log: false
      multi_branch: false
      white_label: false

  - code: basic
    name: Basic
    display_order: 1
    is_public: true
    trial_duration_days: 0
    pricing:
      monthly_bundle_usd: 60
      annual_bundle_usd: 576         # $48/mo equiv
      included_seats: 5
      extra_seat_monthly_usd: 12
      extra_seat_annual_usd: 120     # $10/mo equiv
    caps:
      contacts: 5000
      leads_per_month: 1000
      storage_mb: 5120
      pipelines: 1
      custom_fields_per_entity: 5
      form_widgets: 1
      form_submissions_per_month: 100
      automation_runs_per_month: 0
      api_calls_per_day: 0
      branches: 1
      email_sends_per_month: 1000
      sms_sends_per_month: 0
    features:
      # Basic = same boolean set as trial (intentional — trial gives a taste of Basic)
      # Full key list mirrored from trial above. See plans.yaml.

  - code: standard
    name: Standard
    display_order: 2
    is_public: true
    trial_duration_days: 0
    pricing:
      monthly_bundle_usd: 145
      annual_bundle_usd: 1392        # $116/mo equiv
      included_seats: 5
      extra_seat_monthly_usd: 29
      extra_seat_annual_usd: 276     # $23/mo equiv
    caps:
      contacts: 50000
      leads_per_month: 10000
      storage_mb: 51200
      pipelines: 5
      custom_fields_per_entity: 9999  # "unlimited"
      form_widgets: 10
      form_submissions_per_month: 5000
      automation_runs_per_month: 5000
      api_calls_per_day: 1000
      branches: 1
      email_sends_per_month: 10000
      sms_sends_per_month: 500
    features:
      # Standard unlocks: automation, conversations, WhatsApp, ads, calls.recording,
      # email integration, public API, campaigns, walkins, pipelines, custom fields.

  - code: enterprise
    name: Enterprise
    display_order: 3
    is_public: true
    trial_duration_days: 0
    pricing:
      monthly_bundle_usd: 295
      annual_bundle_usd: 2832        # $236/mo equiv
      included_seats: 5
      extra_seat_monthly_usd: 59
      extra_seat_annual_usd: 588     # $49/mo equiv
    caps:
      contacts: -1                   # -1 = unlimited convention
      leads_per_month: -1
      storage_mb: 524288             # 512 GB
      pipelines: -1
      custom_fields_per_entity: -1
      form_widgets: -1
      form_submissions_per_month: -1
      automation_runs_per_month: -1
      api_calls_per_day: -1
      branches: -1
      email_sends_per_month: 100000
      sms_sends_per_month: 5000
    features:
      # Enterprise unlocks everything in Standard PLUS: SSO, audit log, multi-branch,
      # white-label, AI lead scoring, ads offline conversion sync, unlimited API.
```

**Convention:** `-1` in a cap means "unlimited" (avoids `null` ambiguity). Boolean features default `false` if a key is missing from a plan.

## Backend

| Endpoint | Auth | Behaviour |
|---|---|---|
| `GET /api/v1/plans` | unauthenticated | Returns list of plans where `is_public = true`, sorted by `display_order`. Trial is intentionally hidden — it's not "purchased," it's auto-assigned on signup. Response shape: `{plans: Plan[], currency: "USD", annual_discount_pct: 20}` |
| `GET /api/v1/plans/{code}` | unauthenticated | Returns one plan (any, including trial — for internal use). 404 if unknown code. |

Python module layout:

```
api/src/app/core/billing/
├── __init__.py
├── plans.yaml                 # the source of truth (the data)
├── plans.py                   # Pydantic schemas + loader + plans.get() / plans.all()
├── router.py                  # the two GET endpoints
└── plans_cli.py               # `uv run python -m app.core.billing.plans_cli validate`
```

**Loader behaviour:**
- Reads YAML once at module import, raises on validation failure (process refuses to boot)
- Caches the parsed registry in module-level state
- `plans.reload()` provided for tests that need to mutate

## Frontend

Out of scope for this step. The frontend `/pricing` page is Step 14 and consumes `GET /api/v1/plans` then.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/__init__.py` | created |
| `api/src/app/core/billing/plans.yaml` | created — the four plans, full feature key matrix |
| `api/src/app/core/billing/plans.py` | created — Pydantic schemas + YAML loader + helpers |
| `api/src/app/core/billing/router.py` | created — `GET /plans`, `GET /plans/{code}` |
| `api/src/app/core/billing/plans_cli.py` | created — validate command for CI |
| `api/src/app/main.py` | modified — include `billing.router` under `/api/v1/plans` |
| `api/tests/core/billing/test_plans_registry.py` | created |

**7 files.** Within the per-step rule.

## Tests

`api/tests/core/billing/test_plans_registry.py`:

- **YAML loads cleanly:** `plans.all()` returns 4 plans; codes are `{trial, basic, standard, enterprise}`.
- **Public endpoint hides trial:** `GET /api/v1/plans` returns 3 plans (basic, standard, enterprise), sorted by display_order ascending.
- **By-code endpoint includes trial:** `GET /api/v1/plans/trial` returns the trial plan.
- **404 on unknown code:** `GET /api/v1/plans/free` returns 404.
- **Feature key normalization:** missing feature keys default to `false`; unknown keys cause validation error at load time (catches typos in plans.yaml).
- **Cap convention:** `caps.contacts = -1` is parsed as the "unlimited" sentinel; a positive int stays positive.
- **CLI validate command:** running `plans_cli.py validate` against the real YAML exits 0; against a deliberately-broken fixture exits 1 with a descriptive error.

## Smoke

```
.\API\docker-helper.cmd up
docker exec template_api-api-1 pytest tests/core/billing/test_plans_registry.py -v

# Curl from host:
curl http://localhost:8000/api/v1/plans
# → JSON with 3 plans, trial excluded, USD currency, 20% annual discount.

curl http://localhost:8000/api/v1/plans/trial
# → JSON with the trial plan.

# CI validation:
docker exec template_api-api-1 python -m app.core.billing.plans_cli validate
# → "OK: 4 plans loaded."
```

## Risks

- **YAML drift between docs and code.** The README's feature differentiation table is now a derived view of `plans.yaml`. Future edits must change the YAML and let the README reflect it — not the other way around. Document this at the top of `plans.yaml` with a comment.
- **Float math on prices.** Use integer cents (`monthly_bundle_cents = 6000`) internally, not floats. The YAML uses display USD for readability; the Pydantic loader converts to cents. Annual discount displays as `(1 - annual/monthly*12) * 100` rounded — verify it equals 20 for all paid tiers.
- **`-1` sentinel for unlimited.** Cleaner than `null`, but requires every consumer to remember `if cap == -1: allow_all`. Wrap in a helper: `Cap.is_unlimited(value: int) -> bool`.

## Rollback

Revert the 7 source files. No DB / migration to roll back. No existing data touched. Public endpoints simply stop existing on rollback.
