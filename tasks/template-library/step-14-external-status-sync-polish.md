# Step 14 — External status sync (Celery + webhook + UI badges)

**Goal:** Polish the external-provider status story. Periodic Celery task syncs WA template external_status from Meta. "Refresh status" button in the template detail / editor. Status badges color-coded in list. Webhook handler updates external_status on Meta `message_template_status_update` events (extends existing Step-8 wiring from `whatsapp-platform-upgrade`). Owner notified when a template is rejected or paused by Meta.

**Status:** COMPLETED — Migration `0125_review_external_sync` adds `external_sync` to the `template_review_action` PG enum (autocommit-block `ALTER TYPE … ADD VALUE IF NOT EXISTS`; downgrade no-op since PG can't drop enum values; initial filename `0125_template_review_external_sync` exceeded the 32-char `alembic_version.version_num` limit and was renamed — same pattern as Step 4's `0119_template_review_toggles`). `TemplateReviewAction.external_sync` member added to `core/templates/models.py`. NEW `MetaGraphClient.get_message_template(token, meta_template_id)` queries `/{meta_template_id}?fields=status,rejected_reason,…` and bubbles `MetaGraphError` verbatim. `core/templates/data_access.py` extended with `list_pending_external(org_id)` returning every row whose `external_status` is `pending` or `paused` (the hourly sweep's candidate set — `approved`/`rejected` skipped on purpose). NEW `core/templates/sync.py` (~340 lines): `sync_external_status` resolves WA extension row → calls Meta → maps via `_META_STATUS_TO_EXTERNAL` → writes back to BOTH the central row's `external_status` AND the WA extension's `status` + `last_synced_at` + `rejection_reason` (mirrors the webhook handler so the legacy `/whatsapp/templates` page stays in sync) → writes a `MessageTemplateReview(action=external_sync, note="Meta reports status='X'; reason: …")` audit row; `sync_all_pending` loops over `list_pending_external` with per-template try/except + rollback so one rejected WABA doesn't stall the rest; `prepare_resubmit` flips `(internal=any, external=rejected) → (internal=draft, external=n_a)` with a guard that anything other than `rejected` raises `TemplateError → 409`; `notify_external_status_change` fans a notification to the template's `created_by_user_id` plus every user in the org with the `templates.submit_external` permission (raw SQL joins `tbl_organization_members → tbl_role_permissions → tbl_permissions` keyed on `key='templates.submit_external'`; the result-set dedupes via Python set). NEW `core/templates/tasks.py` — `sync_external_status_all` Celery shared-task (shim pattern for celery-absent dev shells from `health_tasks.py`); SQL pre-filter joins `tbl_integrations + tbl_message_templates` so the sweep only visits orgs that actually have pending templates AND a connected WA integration. `celery_config.py:beat_schedule` gains `templates-sync-external-status` at `crontab(minute=35)` (offset from the `whatsapp-phone-health-refresh` minute=20 and the other hourly sweeps so the worker DB pool doesn't contend). `core/templates/router.py` gains two new endpoints: `POST /api/v1/templates/{id}/sync-external` (gated on `templates.submit_external`, maps `SyncNotSupported → 422` + `MissingExtensionRow → 409` + `TemplateNotFound → 404`) and `POST /api/v1/templates/{id}/resubmit` (gated on `templates.write`). `core/integrations/whatsapp/templates_service.apply_template_status_update` extended: captures `central_before` before mutating, then post-commit fires `notify_external_status_change` when the central row transitioned INTO `rejected` or `paused` (no-op for stable / improving transitions — avoids duplicate notifications on Meta replays). Frontend: `templates-api.service.ts` gains `syncExternal(id)` + `resubmit(id)`. `template-editor.page.ts`: `showRefreshExternalButton` (WA + `external_status !== 'n_a'` + `templates.submit_external`), `showResubmitButton` (WA + `external_status === 'rejected'` + `templates.write`), `rejectionReason` signal populated by `loadExternalStatus(id)` on load for rejected WA rows; `refreshExternalStatus` + `resubmitTemplate` action methods route through `applyTransition` for consistent toast UX. `template-editor.page.html`: 2 new header buttons (`refresh-cw` and `rotate-ccw` icons — `RotateCcw` added to `app.config.ts` registry) + a rose-200 rejection banner under the locked banner showing `rejectionReason()` with a "Resubmit to fix" pointer. Templates list page UNCHANGED — `template-status-badge.component.ts` already shipped the 5 external-status palettes in an earlier step (n_a hidden, pending amber, approved emerald, rejected rose, paused orange). 7 pytest cases in `test_status_sync.py` covering: Meta is called with the right `meta_template_id`, the synced verdict lands on the central row + writes a review audit row, the webhook handler updates the central row, the webhook handler fires the notification on rejected with the rejection reason, `list_pending_external` returns ONLY pending+paused (not approved), the manual-refresh path applies a REJECTED verdict including the reason, and `prepare_resubmit` resets to draft+n_a then refuses a second call. Pytest run deferred per `feedback_pause_before_pytest.md`.
**Depends on:** Step 9 (WA backfill + Meta submission wired). Existing Meta webhook handler at `core/integrations/whatsapp/templates_service.py`.

---

## Scope

In-scope:
- `core/templates/sync.py`:
  - `sync_external_status(org_id, template_id)` — calls the channel adapter's external-status lookup (WA → MetaGraphClient `/message_templates/{id}`). Reads back `status` + `rejection_reason`. Updates central `external_status` + writes a review row of action=`external_sync` for audit.
  - `sync_all_pending(org_id)` — bulk sync for any template where `external_status in ('pending', 'paused')`.
- `core/templates/tasks.py` (Celery):
  - `templates.sync_external_status_all` — periodic task scheduled hourly. Iterates orgs with any pending-external templates and runs `sync_all_pending`.
- Endpoint `POST /api/v1/templates/{id}/sync-external` (extension of the Step-9 endpoint) — manually triggers `sync_external_status`. Gated on `templates.submit_external` (writers + admins).
- Webhook handler extension:
  - The Meta webhook for `message_template_status_update` already lands at `core/integrations/whatsapp/templates_service.apply_template_status_update` (per `whatsapp-platform-upgrade` Step 8). Extend it to also update the central `tbl_message_templates.external_status` whenever the WA extension's status changes.
  - Emit `templates.external_status_changed` audit event.
  - When `external_status` transitions to `rejected` or `paused`, fire a notification via the existing `core/notifications/` engine to the template's creator AND any Owners with `templates.submit_external` perm. Subject: "Template '{name}' was {status} by Meta — {reason}".
- Frontend:
  - Template list page: external_status badge colored — gray `n_a`, amber `pending`, emerald `approved`, red `rejected`, orange `paused`.
  - Template editor header: "Refresh status" button next to the external_status badge (WA + future SMS-DLT only). Calls `POST /sync-external`, shows toast + refreshes the template signal.
  - Rejected templates surface `rejection_reason` on the editor with a "Resubmit" CTA — clicking it moves the template back to draft + clears `external_status` to `n_a`.

Out of scope:
- SMS-DLT sync (no SMS provider configured at this point — Step 12 only captures fields).
- Other channels (email / FB / IG / push) — they have no external state to sync.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/templates/sync.py` | **NEW** |
| `API/src/app/core/templates/tasks.py` | **NEW** — Celery task + beat schedule |
| `API/src/app/core/templates/router.py` | edit — confirm sync endpoint wired (Step 9 stubbed it) |
| `API/src/app/core/integrations/whatsapp/templates_service.py` | edit — `apply_template_status_update` also writes to central row |
| `APP/src/app/features/user/core/templates/templates.page.html` | edit — external_status badge colored |
| `APP/src/app/features/user/core/templates/editor/template-editor.page.ts` | edit — Refresh status button + rejected/Resubmit UX |
| `APP/src/app/features/user/core/templates/editor/template-editor.page.html` | edit — Refresh status button |
| `API/tests/templates/test_status_sync.py` | **NEW** |

**~8 files. ~450 lines.**

## Plan

0. **Data-access layer** (project convention):
   - `core/templates/data_access/templates.py` extended with `list_pending_external(...)` (returns every row where `external_status in ('pending','paused')` for the org, used by the Celery beat task) and `find_by_external_provider_id(...)` (Meta-webhook reverse lookup).
   - Sync orchestration + Meta API calls + audit emits stay in `core/templates/sync.py` (service-side).
1. `sync.py` — channel-dispatched sync logic. WA: call `MetaGraphClient`. SMS/etc: raise `SyncNotSupported`.
2. Celery task — wired into the existing beat schedule (per `whatsapp-platform-upgrade` Step 12 pattern). Hourly cadence.
3. Webhook handler extension — every existing Meta `message_template_status_update` event also updates the central row + fires notifications.
4. Frontend: status badge color map + Refresh button + Rejected/Resubmit UX.
5. Tests: webhook flips central row, periodic sync picks up pending templates, manual refresh works, rejected notification fires.

## DB changes / migrations

None — uses tables from Steps 1, 9.

## Tests

7 pytest cases:
- `test_sync_status_calls_meta_for_wa_template`
- `test_sync_status_writes_central_status`
- `test_webhook_status_update_writes_central_row`
- `test_webhook_status_rejected_emits_notification`
- `test_celery_task_picks_up_pending_only`
- `test_manual_refresh_updates_external_status`
- `test_rejected_template_resubmit_clears_external_status`

## Smoke

```
1. Submit a WA template via Submit to Meta → external_status=pending.
2. Wait for hourly sync OR click Refresh status → external_status updates to Meta's current value.
3. Force a rejection on Meta side (manual test) → webhook arrives → central row external_status=rejected; Owner gets a notification with the rejection reason.
4. List page: rejected templates show red badge; pending templates show amber; approved show emerald.
5. Rejected template: editor shows "Resubmit" button — clicking it moves internal_status back to draft + clears external_status.
```

## Risks

- Periodic sync hammering Meta — at most one call per pending-template per hour per org. Within Meta's rate limits.
- Webhook ordering: a fast rejection-then-approval sequence must not regress to rejected. Use the webhook's `event_time` to drop out-of-order updates.
- Notification fatigue: if 50 templates are rejected at once (unlikely but possible), batch into one digest notification per org-owner pair.

## Self-check (10 rules)

`core/templates/`. ✓ org_id scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions already in place. ✓ pack.yaml untouched. ✓ 8 files / ~450 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 14 — External status sync (Celery + webhook + UI badges)
Files: 8
Verify: hourly sync picks up pending; manual refresh works; rejection notification fires; UI badges colored correctly; Resubmit flow restores draft state.
Tests: 7 pytest cases.

Track complete: 14 steps shipped. Central template library live for WA + Email. SMS / FB / IG / push usable in editor (sends gated on future channel tracks). Settings → Email Templates tab removed. Campaigns + email_sequences both consume generic template_id.

Next track: tasks/automation-engine/.

Awaiting "proceed".
```
