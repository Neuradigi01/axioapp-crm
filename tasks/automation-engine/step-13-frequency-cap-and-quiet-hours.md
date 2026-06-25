# Step 13 — Frequency cap + quiet hours + DPDP suppression check

**Goal:** Send-time enforcement layer. Before any automation run dispatches: check the contact's marketing-consent status (DPDP), check the per-org frequency cap (max N marketing/week/contact), check quiet hours (don't fire 10pm-9am IST by default). Transactional templates bypass all three; marketing templates honor all three.
**Status:** Pending
**Depends on:** Step 4 (dispatcher), Step 13 of `whatsapp-platform-upgrade` (DPDP opt-in capture — already shipped, commit `a1daf3f`).

---

## Scope

In-scope:
- Migration `<ts>_org_compliance_settings.py`:
  - Adds columns to `tbl_organizations`:
    - `quiet_hours_start TIME DEFAULT '21:00:00'`
    - `quiet_hours_end TIME DEFAULT '09:00:00'`
    - `quiet_hours_timezone TEXT DEFAULT 'Asia/Kolkata'`
    - `marketing_frequency_cap_per_week INT DEFAULT 3`
    - `marketing_frequency_cap_enabled BOOL DEFAULT true`
- `core/automation/send_guard.py`:
  - `check_dpdp_suppression(template, contact, db) → (allow, reason)` — for marketing templates: contact must have `whatsapp_opt_in_status='opted_in'` (or appropriate channel-specific consent). Already-implemented opt-in fields used (`whatsapp-platform-upgrade` Step 22).
  - `check_frequency_cap(template, contact, db) → (allow, reason)` — counts marketing-category runs sent to this contact in the last 7 days; rejects if >= cap.
  - `check_quiet_hours(template, org, now_utc) → (allow_now, defer_until)` — if current time in org tz is within quiet hours AND template category is marketing, returns `defer_until=quiet_hours_end`.
  - `evaluate(run) → SendDecision {allow, defer_until?, skip_reason?}` — composite check.
- `core/automation/tasks.py` (extend `deliver_run`):
  - Before sending, call `send_guard.evaluate(run)`.
  - If `defer_until` is set: re-queue the Celery task via `apply_async(eta=defer_until)`; run status stays `queued`.
  - If `skip_reason` is set: write status=`skipped` + error=reason; no send.
- Settings UI extension:
  - `APP/.../core/settings/tabs/automation-settings-tab.component.{ts,html}` — new tab "Send rules" with: quiet hours (start/end + tz) + frequency cap (count + enable toggle) + DPDP marketing-consent policy note.
- Audit events: `automations.send_blocked_dpdp`, `automations.send_blocked_frequency`, `automations.send_deferred_quiet_hours`.

Out of scope:
- Per-contact quiet hours (defer; org-level is enough at v1).
- Per-channel cap (defer; cap is across all marketing channels combined).
- Send-time-optimization (best-time-to-send) — defer.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_org_compliance_settings.py` | **NEW** |
| `API/src/app/core/tenants/models.py` | edit — five new columns |
| `API/src/app/core/tenants/schemas.py` | edit — expose new fields |
| `API/src/app/core/tenants/router.py` | edit — accept new fields in settings PATCH |
| `API/src/app/core/automation/send_guard.py` | **NEW** |
| `API/src/app/core/automation/tasks.py` | edit — wire send_guard into deliver_run |
| `APP/src/app/features/user/core/settings/tabs/automation-settings-tab.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/automation-settings-tab.component.html` | **NEW** |
| `APP/src/app/features/user/core/settings/settings-page.component.html` | edit — add tab |
| `API/tests/automation/test_send_guard.py` | **NEW** |

**~10 files. ~550 lines.**

## Plan

0. **Data-access layer** (project convention):
   - `core/automation/data_access/runs.py` extended with `count_marketing_runs_for_contact(contact_id, *, since)` — the hot-path frequency-cap query.
   - Suppression check reads from `tbl_contacts.whatsapp_opt_in_status` (Step 22 column from `whatsapp-platform-upgrade`) via `core/contacts/data_access/contacts.get_opt_in_status(...)` — extend the existing contacts DAL.
   - Org-level quiet-hours + cap settings read goes in `core/settings/data_access/org_settings.py` as `get_send_rules(org_id)` (create the folder if absent — `core/settings/` doesn't have a data_access yet).
   - `send_guard.evaluate(run)` is composition logic, stays in `core/automation/send_guard.py`.
1. Migration: five columns on `tbl_organizations`.
2. send_guard module: three pure-ish functions + composite.
3. Wire into `deliver_run` Celery task.
4. Audit events on each block/defer.
5. Settings tab UI.
6. Tests: matrix of (category × consent × frequency × quiet-hours) → expected decision.

## DB changes / migrations

One migration: five columns on `tbl_organizations`. Reversible.

## Tests

12 pytest cases:
- Marketing email to opted-out contact → blocked DPDP.
- Marketing email to opted-in contact within cap → allowed.
- Marketing email to opted-in contact past cap → blocked frequency.
- Marketing email during quiet hours → deferred until quiet_hours_end.
- Transactional email anytime → bypass all checks.
- Frequency counts only marketing runs in last 7 days (not transactional, not older).
- Quiet hours respect org timezone (IST default; verified for a UTC-based org).
- Quiet hours that wrap midnight (21:00-09:00) handled correctly.
- Cap=0 means no marketing sends ever.
- Cap_enabled=false bypasses cap.
- Deferred run picks up at the right time.
- Audit events emitted correctly.

## Smoke

```
1. PATCH /api/v1/settings/general {quiet_hours_start: "22:00", quiet_hours_end: "08:00", marketing_frequency_cap_per_week: 2}.
2. Set system clock to 23:00 IST.
3. Publish a fake lead.created event → seeded "Lead Confirmation" trigger fires.
4. tbl_automation_runs: status=queued, scheduled_at advanced to 08:00 next day.
5. Send 2 marketing emails to a contact in a week → 3rd attempt → status=skipped, error="frequency_cap".
6. Send a transactional template (e.g., invoice receipt) → always sends, even at 3am.
7. Opt the contact out → next marketing attempt → status=skipped, error="dpdp_suppressed".
```

## Risks

- Frequency-cap query counts can be slow on tenants with millions of runs — partial index on `(org_id, contact_id, completed_at) WHERE template_category='marketing'` keeps it fast.
- Quiet-hours wrapping midnight is the most error-prone branch. Test extensively.
- Deferring runs en masse during quiet hours can cause a "wake-up burst" at quiet_hours_end. Acceptable at v1; jitter (random 0-30min) can be added later if needed.

## Self-check (10 rules)

`core/automation/` + `core/tenants/`. ✓ org_id propagated. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions already registered. ✓ pack.yaml untouched. ✓ 10 files / ~550 lines — at Rule 8 upper bound; justified by the matrix-tested compliance layer. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 13 — Frequency cap + quiet hours + DPDP suppression check
Files: 10
Verify: marketing sends honor DPDP + cap + quiet hours; transactional bypasses; Settings UI exposes the controls.
Tests: 12 pytest cases.
Awaiting "proceed".
```
