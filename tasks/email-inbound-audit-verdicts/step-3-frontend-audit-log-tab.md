# Step 3: Frontend — platform-admin audit log tab

**Status:** Pending

## Goal

Read-only audit log for platform administrators. Paginated, filterable by outcome + date-range. No row detail modal in v1 (no payload to show).

## Files touched

- `APP/src/app/features/user/core/settings/email/audit-log-tab.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/audit-log.service.ts`
- `api/src/app/core/email/mailgun/router.py` — extend with admin GET endpoint
- `APP/src/app/features/user/core/settings/tabs/email-settings-tab.component.ts` — register tab (visible only to `platform.admin`)

## What this step does

- Backend endpoint:
  - `GET /api/v1/admin/email-inbound-deliveries`
  - Permission gate: `platform.admin` permission (not per-org Owner — this is platform-level).
  - Query params: `outcome=<enum>`, `from=<iso>`, `to=<iso>`, `page`, `page_size` (max 100).
  - Default sort: `received_at DESC`.
  - Response: paginated list of audit rows with `id, received_at, signature_status, replay_status, timestamp_status, outcome, mailgun_delivery_id, recipient, sender, payload_size_bytes, attachment_count, client_ip`.
- Frontend tab:
  - Visible only if current user has `platform.admin` permission (checked via existing permission service).
  - Filter chips: outcome enum (All / Enqueued / Signature rejected / Replay rejected / Timestamp rejected / Size rejected).
  - Date range picker (default: last 24h).
  - Table columns: received_at, outcome (badge), from, to, size, signature_status, replay_status, client_ip.
  - Pagination: page-size dropdown 25 / 50 / 100.
  - No row-detail modal in v1 — metadata is all we have.
- Service: `list({outcome, from, to, page, pageSize})` → `GET /api/v1/admin/email-inbound-deliveries`.

## Tests

**Backend:**
- `test_admin_endpoint_requires_platform_admin_permission`
- `test_admin_endpoint_returns_403_for_regular_owner`
- `test_admin_endpoint_paginates_by_received_at_desc`
- `test_admin_endpoint_filters_by_outcome_enum`
- `test_admin_endpoint_filters_by_date_range`
- `test_admin_endpoint_max_page_size_100`
- `test_admin_endpoint_rejects_unknown_outcome_400`

**Frontend (Karma):**
- `test_audit_list_requires_platform_admin_permission`
- `test_audit_list_hides_tab_for_non_admin_users`
- `test_audit_list_paginates_by_date_desc`
- `test_audit_list_filters_by_outcome_enum`
- `test_audit_list_no_row_detail_modal_in_v1`

## Verification checklist

- [ ] All 12 tests pass
- [ ] Prettier applied
- [ ] Lucide icons registered
- [ ] Tab hidden for non-platform-admin users
- [ ] Manual smoke: platform admin sees rows; regular Owner sees no tab; date filter works; outcome filter works
- [ ] `ng build` clean

## Self-check

- Rule 4 (permissions): pass — server-side `platform.admin` check.
- Rule 2 documented deviation (no org_id on audit table): pass — system-level per Step 1.
- Memory `feedback_prettier_on_write.md`: pass.
- Memory `feedback_lucide_icon_registry.md`: pass.

## Stop-and-report

Report test pass, browser smoke output showing admin-only visibility. **Track 6 done. All 6 tracks planning-tier complete. Awaiting your "proceed" — the next step is implementation.**
