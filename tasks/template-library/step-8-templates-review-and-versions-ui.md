# Step 8 — Review modal + versions drawer + test-send modal

**Goal:** UI for the workflow transitions (Step 4) and the test-send flow (Step 5). Plus a versions drawer for browsing the history written in Step 2.
**Status:** Pending
**Depends on:** Step 4 (workflow endpoints), Step 5 (test-send endpoint), Step 7 (editor page hosts the trigger buttons).

---

## Scope

In-scope:
- `APP/.../core/templates/review/template-review.modal.{ts,html}`:
  - Mounted from the editor page header when `internal_status in (in_review)` and current user has `templates.review` perm.
  - Three action buttons: Approve / Request Changes / Reject.
  - Note field (required for Reject + Request Changes; optional for Approve).
  - On success, refreshes the editor's template signal.
- `APP/.../core/templates/versions/versions-drawer.component.{ts,html}`:
  - Right-side drawer triggered by the editor's "Versions" button.
  - Lists every version (descending by version number) with: version #, changed-by avatar + name, changed-at, change-note, "View" button.
  - "View" opens the version in a read-only preview overlay (uses Step-7's preview-pane component).
  - "Restore" button (gated on `templates.write`) — POSTs `PATCH /templates/{id}` with the past version's body + subject; creates a new version, doesn't roll back.
- `APP/.../core/templates/test-send/test-send.modal.{ts,html}`:
  - Recipient input (validated per channel — phone for WA/SMS, email for Email).
  - Optional sample-context JSON editor (collapsed by default).
  - Submit → POST `/templates/{id}/test-send`. Shows result (success + channel_message_id, or error message from the adapter).
  - Mounted from editor header "Test send" button.
- Editor page (Step 7) gains four header buttons + plumbing:
  - **Versions** — opens versions drawer.
  - **Test send** — opens test-send modal.
  - **Submit for review** — POSTs `/submit` (visible when `internal_status=draft` and user has `templates.write`).
  - **Review** — opens review modal (visible when `in_review` and user has `templates.review`).
  - **Publish** — POSTs `/publish` (visible when `approved` and user has `templates.publish`).
  - **Archive** — POSTs `/archive` (visible when not already archived).
- Jest smoke for each modal + drawer.

Out of scope:
- External submission (Submit to Meta) — Step 9.
- Side-by-side version diff — defer; "View" of a single version is enough at v1.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/templates/review/template-review.modal.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/review/template-review.modal.html` | **NEW** |
| `APP/src/app/features/user/core/templates/versions/versions-drawer.component.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/versions/versions-drawer.component.html` | **NEW** |
| `APP/src/app/features/user/core/templates/test-send/test-send.modal.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/test-send/test-send.modal.html` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/template-editor.page.ts` | edit — wire header buttons + modals |
| `APP/src/app/features/user/core/templates/editor/template-editor.page.html` | edit — header buttons |
| `APP/src/app/features/user/core/templates/review/template-review.modal.spec.ts` | **NEW** |

**~9 files. ~500 lines.**

## Plan

1. Three small modal/drawer components — each ~60 lines TS + ~40 lines HTML.
2. Editor header buttons: visibility logic via `computed()` against the template's `internal_status` + the current user's perm set.
3. Wire each button to its modal via Angular Material `MatDialog` (already in use elsewhere in the project).
4. Jest: each modal renders, validates inputs, calls the right API method on submit.

## DB changes / migrations

None.

## Tests

5 Jest cases:
- Review modal — Reject button disabled when note empty.
- Test-send modal — recipient validated per channel.
- Test-send modal — submit shows success state with channel_message_id.
- Versions drawer — lists versions descending; "View" shows the past body in preview.
- Editor header — buttons appear/disappear correctly based on status + perm.

## Smoke

```
1. As Owner: open a draft template → Submit for review button visible → click → status flips to in_review.
2. Switch to Reviewer (different user with templates.review): open the same template → Review button visible → Approve with no note → status flips to approved.
3. Publish button now visible → click → status flips to published.
4. Click Test send → modal opens → enter recipient → submit → message arrives + audit row created.
5. Click Versions → drawer opens → click View on v1 → preview shows v1 body.
6. As Employee (read-only): all action buttons hidden; only Versions is visible.
```

## Risks

- Modal stacking — review modal triggered from editor, version-restore confirm modal from versions drawer. `MatDialog` handles z-index automatically.
- Auto-save (Step 7) creates a new version while versions drawer is open — drawer must re-fetch on open.

## Self-check (10 rules)

`features/user/core/templates/`. ✓ org_id auto-applied. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Sidebar already registered. Permissions gate every button. ✓ pack.yaml untouched. ✓ 9 files / ~500 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 8 — Review modal + versions drawer + test-send modal
Files: 9
Verify: full review flow + test send + version history navigable end-to-end.
Tests: 5 Jest cases.
Awaiting "proceed".
```
