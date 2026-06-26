# Step 17 — Version history + rollback + import/export JSON

**Goal:** Every workflow edit creates a row in `tbl_workflow_versions` (Step 1 schema). This step adds the version-history UI (drawer), one-click rollback, and JSON import/export. Operators can revert a broken workflow to last week's state in one click, or share a workflow definition cross-org.
**Status:** Pending
**Depends on:** Step 2 (service writes versions on update). Step 14 (canvas page hosts the version drawer trigger).

---

## Scope

In-scope:

- Backend:
  - `GET /api/v1/workflows/{id}/versions` — paginated list of versions (newest first). Each: `{id, version, change_note, created_by_user_id, created_at}`. Gated on `workflows.read`.
  - `GET /api/v1/workflows/{id}/versions/{version}` — full graph + metadata for one version. Gated on `workflows.read`.
  - `POST /api/v1/workflows/{id}/rollback` body `{target_version: int, change_note?: str}` — copies the target version's graph into the current row, bumps `current_version` (so rollback ITSELF lands as a new version, preserving the audit chain). Gated on `workflows.write`. Refuses on active marketing workflows (same lock as Step 2's update).
  - `GET /api/v1/workflows/{id}/export` — returns the workflow as a portable JSON dict: `{name, description, category, graph, re_enrollment_rule, is_marketing, schema_version: 1}`. Internal IDs (template_id references, contact-related IDs) are kept but documented as "remapping required at import time". Gated on `workflows.read`.
  - `POST /api/v1/workflows/import` body `{json: {...}, target_folder_id?: UUID, name?: str}` — validates the JSON shape, remaps unknown template_ids to NULL (the importer becomes the new owner), creates a draft. Gated on `workflows.write`.

- `core/workflows/data_access.py` extended:
  - `list_versions(session, *, workflow_id, limit, offset)`.
  - `get_version(session, *, workflow_id, version)`.
  - `add_version` (already exists from Step 2).

- `core/workflows/service.py` extended:
  - `rollback_workflow(session, *, org_id, user_id, workflow_id, target_version, change_note)` — fetches target version's graph + validates it (in case template_ids have since been archived) + writes new version + updates `tbl_workflows.graph` to the rolled-back content + bumps `current_version`.
  - `export_workflow(session, *, org_id, workflow_id) -> dict` — pure dict serializer.
  - `import_workflow(session, *, org_id, user_id, payload, target_folder_id, name)` — validates shape via Pydantic; runs the graph validator; remaps template references; persists as draft v1.

- Frontend:
  - `app/src/app/features/user/core/workflows/canvas/version-history-drawer.component.{ts,html}` — opens from the canvas header. Lists versions newest-first; each row: version number, change_note, created_by (resolved to user name via existing `lookup_user_by_uuid`), created_at, "View" + "Restore" buttons.
  - "View" opens a read-only canvas overlay showing the historical graph; "Back to current" returns. "Restore" triggers POST /rollback + closes the drawer + reloads the canvas with the rolled-back graph.
  - "Export JSON" + "Import JSON" buttons on the canvas header. Export downloads `<workflow-name>.workflow.json`. Import opens a file picker → POSTs the file → navigates to the new draft.

- Version-history change_note input — when the operator saves a draft, a small modal asks "Describe this change (optional)". Auto-fills with "Edited at <time>" if blank. The change_note lands on the version row.

Out of scope:

- Diffing two versions side-by-side — v2 polish. Operators see the change_note + can preview each version individually.
- Cross-version conflict resolution — workflows aren't multi-user-edited concurrently (the canvas auto-save handles single-user dirty state); two operators editing in parallel race the latest-wins.
- Pinning a version — every version is preserved indefinitely; no GC.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/router.py` | edit — 4 new endpoints |
| `API/src/app/core/workflows/service.py` | edit — rollback / export / import functions |
| `API/src/app/core/workflows/data_access.py` | edit — version helpers |
| `API/src/app/core/workflows/schemas.py` | edit — `WorkflowExport`, `WorkflowImport`, `RollbackPayload` |
| `APP/src/app/features/user/core/workflows/canvas/version-history-drawer.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/import-modal.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/save-change-note.modal.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/workflows-api.service.ts` | edit — versions + rollback + import/export wrappers |
| `API/tests/workflows/test_version_history.py` | **NEW** |

**~9 files. ~600 lines.**

## Plan

1. DAL extensions for versions.
2. Service rollback / export / import.
3. Router endpoints.
4. Version-history drawer + import modal + change-note modal.
5. Tests: rollback writes new version; export round-trips through import; rollback to invalid version refuses; rollback bumps current_version.

## DB changes / migrations

None.

## Tests

10 pytest + 2 Jest cases:

- (pytest) `list_versions` returns newest-first.
- (pytest) `rollback_workflow` writes a new version with the rolled-back graph.
- (pytest) `rollback_workflow` to non-existent version → 404.
- (pytest) `rollback_workflow` on active marketing workflow → 409.
- (pytest) `export_workflow` returns the documented schema.
- (pytest) `import_workflow` validates JSON shape.
- (pytest) `import_workflow` remaps unknown template_ids to NULL.
- (pytest) Round-trip: export then import = same graph.
- (pytest) Rollback preserves the audit chain (current_version after rollback > current_version before).
- (pytest) Change_note text persisted on each save.
- (Jest) Version drawer lists newest-first.
- (Jest) Import modal validates file shape before posting.

## Smoke

```
1. Edit a workflow several times → version_history drawer shows multiple rows.
2. Click v3 → preview overlay shows the historical graph.
3. Click "Restore" → new version 5 written; canvas reflects v3's content.
4. Click Export → downloads workflow.json.
5. Click Import in another org → uploads same JSON → new draft created.
6. Confirm template references in the new draft are nullified.
```

## Risks

- Workflow size in JSON form — a workflow with 50 nodes ~ 30-60 KB. Acceptable for import / export.
- Schema versioning: today's export carries `schema_version: 1`. If we evolve the graph shape, migrations between schema versions are needed at import time. Document in the importer's docstring.
- Rollback of a workflow that's been active for months may have stale template references (templates archived since); rollback's graph validator surfaces the issue + the operator fixes before re-activating.

## Self-check (10 rules)

`core/workflows/` + frontend. ✓ org_id-scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced (write for rollback/import; read for list/export). pack.yaml untouched. ✓ 9 files / ~600 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 17 — Version history + rollback + import/export JSON
Files: 9
Verify: every save lands a version row; rollback restores + preserves audit chain; export → import round-trip; import remaps unknown template_ids.
Tests: 10 pytest + 2 Jest.
Awaiting "proceed".
```
