# Step 6.5 — Tests

**Goal:** Coverage pass — unit tests for services, integration tests for APIs (auth, custom fields, pipelines, walk-ins, leads, custom orders), Cypress E2E for the critical flows (login → create lead → book appointment → convert).
**Phase:** 6
**Depends on:** prior phases
**Status:** Pending

## Scope
**In-scope:**
- Backend unit + integration test coverage target: 80% line / 70% branch.
- E2E: `e2e/` folder using **Playwright** (not Cypress — better Angular support, modern; if user prefers Cypress, swap).
  - `auth.spec.ts` — login + 2FA + logout.
  - `lead-flow.spec.ts` — create contact → create lead → drag stage → book appointment → mark won.
  - `pos.spec.ts` — POS checkout flow.
  - `custom-order.spec.ts` — create custom order → upload photo → move stage → mark delivered.
- CI integration: `.github/workflows/test.yml` runs both backend + e2e.

## Files to touch
- `api/tests/...` (added/modified — coverage)
- `e2e/playwright.config.ts` (created)
- `e2e/specs/*.spec.ts` (created)
- `.github/workflows/test.yml` (created)

## Plan
1. Identify gaps with `pytest --cov`; add tests until target.
2. Bootstrap Playwright; configure to run against `docker-compose -f docker-compose.test.yml`.
3. Seed a known dataset for E2E.
4. CI workflow.

## Tests to add
- See above.

## Verification checklist
**Backend:**
- run: `pytest --cov=app --cov-report=term-missing` → ≥80% line.
- run: `npx playwright test` → all green.

## Self-check (10 rules)
- [ ] No flaky tests.

## Stop & report
Await "proceed" before Step 6.6.
