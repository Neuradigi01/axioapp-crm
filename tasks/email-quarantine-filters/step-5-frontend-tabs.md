# Step 5: Frontend — Quarantine tab + Blocklist tab + modal + service

**Status:** COMPLETED (2026-09-21) — `QuarantineService` (Angular HTTP wrapper for 7 endpoints across filter-rules + quarantine) + two standalone components: `QuarantineTabComponent` (filter chips by reason_code, row-inline Release/Discard with spam-verdict confirm + virus-verdict release-hidden, bulk-release toolbar enabled ONLY when every selected row is `rate_capped` per plan) + `BlocklistTabComponent` (rule list with allow/block filter chips, add-rule modal with segment controls for type/kind + per-kind placeholder hint, delete confirmation). Amber warning banner pattern reused per memory. Standalone components use signals + `@if`/`@for`/`ChangeDetection.OnPush` per Angular 20+ conventions.

## Goal

Operator surfaces for both quarantine review and filter-rule management. Owner/Admin gated.

## Files touched

- `APP/src/app/features/user/core/settings/email/quarantine-tab.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/quarantine-row.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/blocklist-tab.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/filter-rule-modal.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/quarantine.service.ts`

## What this step does

- Quarantine tab:
  - Filter chips by reason_code (All / Size / Blocked / Rate-capped / Spam / Virus).
  - Table: From, To, Subject snippet, Reason chip, Held (relative time), per-row actions (Release / Discard).
  - Row detail on click: full sender, subject, body snippet, attachment list.
  - Bulk-select toolbar: "Release all rate-capped" button. Enabled only when selection is homogeneous `rate_capped`.
  - Virus rows: Release button hidden; only Discard.
  - Spam rows: Release button shows confirm modal ("You confirm this is not spam").
- Blocklist tab:
  - Header: "Filter rules", "+ Add rule" button.
  - Table: rule type (allow/block), match kind, match value, applies to (org-wide / endpoint), created by, actions (Delete).
  - Filter chips: All / Allow / Block.
- Filter rule modal:
  - Type: allow / block (segmented control).
  - Match kind: email address / domain / contact flag (segmented).
  - Value input: inline validation per kind.
  - Applies to: org-wide (default) or dropdown of endpoints.
  - Label (optional).
  - Submit → POST → refresh list.
- Service:
  - `quarantine.list({status, reason_code, page})`
  - `quarantine.release(id)`
  - `quarantine.discard(id)`
  - `quarantine.bulkRelease(ids)`
  - `filterRules.list()`
  - `filterRules.create(payload)`
  - `filterRules.delete(id)`
- HTTP retry interceptor applies for GETs.

## Tests (Karma)

- `test_quarantine_list_renders_by_reason_code_chip`
- `test_release_button_confirms_on_spam_verdict`
- `test_release_button_hidden_on_virus_verdict`
- `test_bulk_release_toolbar_greyed_on_non_rate_capped_selection`
- `test_bulk_release_toolbar_enabled_on_homogeneous_rate_capped`
- `test_blocklist_add_rule_modal_validates_inline`
- `test_blocklist_rule_delete_confirms`
- `test_filter_modal_segment_controls_switch_kind_and_type`
- `test_filter_modal_submit_refreshes_list`
- `test_row_detail_expand_shows_full_subject_and_attachments`

## Verification checklist

- [ ] All 10 Karma tests pass
- [ ] Prettier applied
- [ ] Lucide icons registered
- [ ] Manual smoke at Ajay's Workspace: send test message from blocked domain → confirm quarantine → release → confirm arrives in conversation
- [ ] `ng build` clean

## Self-check

- Rule 4: pass — server-side auth.
- Memory `feedback_prettier_on_write.md`: pass.
- Memory `feedback_standard_warning_banner_pattern.md`: pass.
- Memory `feedback_lucide_icon_registry.md`: pass.

## Stop-and-report

Report Karma pass, browser smoke output. **Track 5 done. Awaiting your "proceed" for Track 6 step 1.**
