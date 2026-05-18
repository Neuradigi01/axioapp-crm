# Step 5.13 — Beta cutover

**Goal:** Final QA. Demo data scrub. First customer onboarding script.
**Phase:** 5 — Core CRM v1 Launch
**Depends on:** 6.1–6.8
**Status:** Pending

## Scope
**In-scope:**
- Demo data scrub script: removes seed/test rows, leaves only the real customer's organization.
- Onboarding script: provisions a new org from a CSV (org name, GST, address, owner email/phone, role assignments) and runs the furniture pack installer.
- Pre-launch checklist:
  - All RLS policies in place.
  - All migrations applied.
  - Backup tested (restore on staging).
  - Sentry receiving events.
  - Prometheus scraping.
  - SSL valid.
  - Login tested with real owner account.
  - WhatsApp Business connected.
  - At least one inventory item, one lead, one walk-in created.
- Final security pass: dependencies updated, no critical CVEs.
- Go-live runbook.

## Files to touch
- `scripts/scrub_demo_data.py` (created)
- `scripts/onboard_new_org.py` (created)
- `docs/go-live-runbook.md` (created)

## Plan
1. Scrub script preview-mode + apply-mode.
2. Onboarding script idempotent (re-runnable).
3. Walk through pre-launch checklist on staging, then prod.

## Tests to add
- `tests/test_scrub_dryrun.py` — preview-mode lists rows; doesn't delete.

## Verification checklist
- All checklist items ✓.
- One real org provisioned and tested end-to-end.

## Self-check (10 rules)
- [ ] No demo data in prod.
- [ ] All 10 rules verified one last time.

## Stop & report
This concludes the entire FurnitureCRM build. Document handover, hand off to operations.
