# Step 6.6 — Observability

**Goal:** Structured logs with request IDs, basic metrics (Prometheus), error tracking (Sentry). Health & readiness endpoints.
**Phase:** 6
**Depends on:** prior phases
**Status:** Pending

## Scope
**In-scope:**
- Backend:
  - Request-ID middleware (already partly in 1.4) — propagate across logs and into Celery tasks.
  - Prometheus metrics: request count/latency by route, DB pool, Celery queue depth, AI provider latency. Endpoint `/metrics` (admin-only IP allowlist or basic auth).
  - Sentry SDK init (DSN from env).
  - Endpoints: `/health` (already there), `/readiness` (DB ping + Redis ping).
- Frontend:
  - Sentry SDK init (separate DSN).
  - Source map upload in production build.

## Files to touch
- `api/app/shared/observability/{__init__,prometheus,sentry}.py` (created)
- `api/app/shared/middleware.py` (modified — request id propagation)
- `api/app/celery/__init__.py` (modified — request id propagation)
- `app/src/app/features/user/core/observability/sentry.ts` (created)
- `app/angular.json` (modified — source maps)

## Plan
1. Add `prometheus-fastapi-instrumentator`.
2. Add `sentry-sdk` for FastAPI + Celery.
3. Frontend: `@sentry/angular`.
4. Readiness endpoint with timeouts.

## Tests to add
- `tests/test_metrics.py` — `/metrics` returns Prometheus format.
- `tests/test_readiness.py` — 200 when DB+Redis up; 503 when down.

## Verification checklist
**Backend:**
- `/metrics` works.
- intentional error → Sentry receives event.
- request id present in JSON logs.

## Self-check (10 rules)
- [ ] No PII in logs.

## Stop & report
Await "proceed" before Step 6.7.
