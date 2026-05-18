# Phase 5 — Core CRM v1 Launch

**Goal:** Everything the core CRM template needs to ship a v1 to a real external customer — the landing dashboard, a handful of polish features, and the production-hardening work (RLS, tests, observability, deployment, docs, cutover).

**Phase completion criteria:** A non-furniture business can clone the repo, follow the docs, deploy, log in as their org admin, invite teammates, manage roles, and use the layered core modules in production. Multi-tenant isolation is enforced. Email actually delivers. There are tests and logs.

This phase intentionally contains **no Layer-2 furniture-pack work** — that lives in [Phase 6](../phase-6-furniture-pack-features/README.md) and is post-launch.

---

## Core CRM v1 features (4 steps)

Features that live on the core CRM platform itself — every adopter benefits regardless of vertical.

| # | Title | Priority | Status |
|---|---|---|--------|
| 5.1 | [Admin Dashboard overview](step-5.1-admin-dashboard.md) | **SHOULD** — every CRM expects a landing dashboard; today `/user` is just a welcome page | Pending |
| 5.2 | [AI Chatbot in Conversations](step-5.2-ai-chatbot.md) | NICE — v2 feature; no v1 CRM ships an AI chatbot | Pending |
| 5.3 | [AI Auto Follow-up Schedule](step-5.3-ai-followups.md) | NICE — v2; follow-up rules can stay manual in v1 | Pending |
| 5.4 | [Reviews automation](step-5.4-reviews-automation.md) | NICE — Reviews module already exists (Phase 3); this just auto-fires after delivery | Pending |

## Polish (3 steps)

Nice-to-have improvements every CRM eventually has. None blocks v1 launch.

| # | Title | Priority | Status |
|---|---|---|--------|
| 5.5 | [Reporting / Analytics depth](step-5.5-reporting.md) | NICE — defer until customers ask | Pending |
| 5.6 | [Global search](step-5.6-search.md) | NICE — defer until data volume makes "five clicks" painful | Pending |
| 5.7 | [Performance pass](step-5.7-performance.md) | NICE — premature without real users + real data; profile real bottlenecks rather than guess | Pending |

## Required for v1 ship (6 MUST steps)

The actual ship-blockers. If your goal is "first real beta customer on a deployed instance," every one of these is required.

| # | Title | Priority | Status |
|---|---|---|--------|
| 5.8 | [RLS hardening](step-5.8-rls-hardening.md) | **MUST** — multi-tenant isolation; today the dev postgres role bypasses RLS. Second tenant logging in is unsafe. | Pending |
| 5.9 | [Tests](step-5.9-tests.md) | **MUST** — auth + RBAC + Phase 2.5 admin CRUD need coverage. The pytest conftest is currently broken since DR.7 — fix that first. | Pending |
| 5.10 | [Observability](step-5.10-observability.md) | **MUST** (minimum) — structured logs + error reporting. Full traces can wait. | Pending |
| 5.11 | [Deployment](step-5.11-deployment.md) | **MUST** — production Docker compose, real SMTP (the invite flow's email currently only logs), HTTPS, secrets. | Pending |
| 5.12 | [Documentation](step-5.12-documentation.md) | **MUST** (minimum) — README + env reference + clone-migrate-seed-login walkthrough. | Pending |
| 5.13 | [Beta cutover](step-5.13-beta-cutover.md) | **MUST** — process step; mostly checklist work for the first real customer. | Pending |

---

## Outside Phase 5 but still must-do before v1 ship

- **DR.6 soak revisit** — drop `users` table, finish FK retargeting. See [`../phase-4.5-demo-roles-setup/README.md`](../phase-4.5-demo-roles-setup/README.md). Scheduled for **2026-05-29**.
- **Email backend swap** — replace `LogEmailBackend` with a real SMTP / SES backend. Belongs to 5.11 (Deployment) but worth calling out separately because the invite flow (Phase 2.5.6) silently fails to deliver mail until this lands.
- **pytest conftest fix from DR.7** — the existing test fixtures still build `User(id=UUID, org_id=…, email=…)` against the pre-DR.7 schema. Must be fixed before 5.9 (Tests) can add anything new.

## Recommended order for v1

1. Fix the broken pytest conftest from DR.7 (housekeeping, ~30 min).
2. **5.8** — RLS hardening (security gate).
3. **5.9** — Tests for auth + RBAC + admin CRUD.
4. **5.10** — Structured logs + error reporting.
5. **5.11** — Production deployment + real SMTP wired into the invite flow.
6. **5.12** — README + env reference + ops runbook.
7. **5.1** — Admin dashboard (every CRM expects a landing dashboard).
8. **DR.6 soak cleanup** — drop `users` table, finish FK retargeting.
9. **5.13** — Beta cutover with the first real customer.

The NICE-tier items (5.2, 5.3, 5.4 AI/automation + 5.5, 5.6, 5.7 polish) can ship in v1.1+ once you have real customers driving prioritisation.

## Dependencies

- 5.1 (Dashboard) depends on most prior modules being live (it pulls KPIs, leads, appointments, conversations).
- 5.2 (AI Chatbot) depends on 3.10 (conversations frontend) and 3.8 (channel registry).
- 5.3 (AI follow-ups) depends on Celery beat (Phase 1) + any follow-up templates the vertical pack contributes.
- 5.4 (Reviews automation) depends on 3.13 (reviews) + 3.15 (campaigns).
- 5.8–5.13 (hardening) are mostly independent. Recommended order above.
