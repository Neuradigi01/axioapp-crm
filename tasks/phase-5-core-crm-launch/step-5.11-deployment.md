# Step 5.11 — Deployment

**Goal:** Production Dockerfiles for backend and frontend. `docker-compose.prod.yml`. Environment-based configs. Deployment runbook.
**Phase:** 5 — Core CRM v1 Launch
**Depends on:** all prior
**Status:** Pending

## Scope
**In-scope:**
- `api/Dockerfile.prod` — multi-stage, non-root user, no dev deps.
- `app/Dockerfile.prod` — multi-stage build, nginx serve.
- `docker-compose.prod.yml` — db, redis, api, app (nginx), celery_worker, celery_beat, optional reverse proxy (Caddy or nginx).
- TLS: relies on a reverse proxy (Caddy with auto-LE recommended); document.
- `docs/deployment.md` runbook with: env vars, first-deploy checklist, migration steps, rollback strategy.
- DB backup script (`scripts/backup_db.sh`).

## Files to touch
- `api/Dockerfile.prod` (created)
- `app/Dockerfile.prod` + `app/nginx.conf` (created)
- `docker-compose.prod.yml` (created)
- `Caddyfile.example` (created)
- `docs/deployment.md` (created)
- `scripts/backup_db.sh` (created)

## Plan
1. Multi-stage Dockerfiles.
2. Compose with health checks + restart policies.
3. Caddyfile sample for HTTPS termination.
4. Runbook covers: cold start, migrations, backup, rollback, secret rotation.

## Tests to add
- `tests/test_compose_smoke.sh` — boots prod compose and hits `/health`.

## Verification checklist
**Deployment:**
- `docker compose -f docker-compose.prod.yml up -d` → all services healthy.
- visit `/api/v1/health` and frontend → 200.

## Self-check (10 rules)
- [ ] Secrets not baked into images.
- [ ] No `.env` files in images.

## Stop & report
Await "proceed" before Step 6.8.
