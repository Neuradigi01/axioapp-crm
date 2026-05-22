# Step 4 — Frontend: upload page + source-platform selector

**Goal:** Build `/user/leads/import` — a page with a file picker, a source-platform dropdown, an optional name field, and an Upload button. On successful upload, route to the mapping page (Step 5) carrying the new import id.
**Track:** Bulk Import
**Status:** Pending
**Depends on:** Steps 1–3 (backend complete), Phase 1.5 (permissions on the frontend), the manual-lead-entry track's badge styling (for visual consistency on the leads page link).

---

## Scope

In-scope:

- New route `/user/leads/import` rendered by `UploadPageComponent`.
- New menu entry "Import leads" under the leads sub-menu (or as an inline button on the leads page header — implementer's call based on existing layout).
- Form:
  - File input (drag-and-drop area + click-to-browse). Accepts `.csv`, `.xlsx`. Visual preview of filename + byte size after selection.
  - Source platform dropdown: `Zoho | HubSpot | Salesforce | Freshsales | Generic CSV | Custom`.
  - Optional name input (placeholder: "Auto-named from filename if blank").
- Upload button: disabled until file selected and platform chosen. On click, calls `POST /leads/import/upload` (multipart). Shows a spinner during upload.
- On success → `router.navigate(['/user/leads/import', importId, 'mapping'])` (Step 5 renders that route).
- On error (size cap, mime, row cap, network): inline error banner with the server's error message.
- Route guard: `leads.import` permission. Without it, redirect to Access Denied.
- `imports-api.service.ts` — typed Angular service wrapping the 6 endpoints from Steps 1–3.

Out of scope:

- No mapping UI — Step 5.
- No history page — Step 6.
- No drag-and-drop reordering, multi-file, or zip support.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/leads/import/upload-page.component.ts` | created |
| `app/src/app/features/user/core/leads/import/upload-page.component.html` | created |
| `app/src/app/features/user/core/leads/import/imports-api.service.ts` | created — typed wrappers for all 6 endpoints |
| `app/src/app/features/user/core/leads/leads.routes.ts` | modified — add `/import`, `/import/:id/mapping`, `/import/:id/result`, `/import-history` |
| `app/src/app/features/user/layout/sidebar.component.html` (or wherever leads menu lives) | modified — add "Import leads" link |

**5 files.** Inside rule-8 budget.

## Plan

1. Generate `imports-api.service.ts` mirroring the backend endpoints. Use the existing `inject(HttpClient)` pattern; reuse the shared `ApiBase` if there is one.
2. Build `UploadPageComponent` as a standalone signal-based component:
   - `selectedFile = signal<File | null>(null)`
   - `sourcePlatform = signal<SourcePlatform>('zoho')`
   - `name = signal<string>('')`
   - `uploading = signal(false)`
   - `error = signal<string | null>(null)`
   - `canSubmit = computed(() => this.selectedFile() && this.sourcePlatform() && !this.uploading())`
3. Drag-and-drop: standard `(dragover)`/`(drop)` handlers on the file zone. Visual state shows `border-2 border-dashed border-indigo-400` when active.
4. On submit, build FormData and POST. On 201, navigate to `/user/leads/import/:id/mapping`.
5. Add the route entry in `leads.routes.ts`. Add the sidebar menu entry, guarded by `*ngIf="perms.has('leads.import')"`.

## Tests

Manual smoke per checklist. If existing frontend has unit tests for similar pages, add one to assert the upload button is disabled until both file and platform are set.

## Smoke (browser)

```
1. Log in as Owner. Sidebar shows "Import leads" under Leads.
2. Click it. Page renders with file zone + platform dropdown + name input.
3. Drag a 100KB sample CSV onto the zone. Filename and size appear.
4. Pick "Zoho". Upload button enables.
5. Click Upload. Spinner. ~1s later, page navigates to /user/leads/import/<uuid>/mapping
   (Step 5 page; if Step 5 isn't built yet, an empty placeholder is acceptable for this step).
6. Repeat with an 11MB file → after Upload, an inline error appears with the
   413 body's detail message ("File exceeds 10 MB cap").
7. Repeat with a PDF → 415 error displayed inline.
8. Log in as Employee (no leads.import). Sidebar does NOT show "Import leads".
   Direct visit to /user/leads/import → Access Denied page.
```

## Risks

- **Step-5 page not built yet** while testing this step in isolation — accept this and stub the mapping route with a minimal placeholder component, deletable in Step 5. Document the stub in this step's stop-report so reviewer knows it's expected.
- **Drag-and-drop accessibility:** make sure the file input is keyboard-reachable too. Use a `<label for="file-input">` pattern with the input visually hidden but focusable. Plain click-to-browse still works.
- **Sidebar layout drift:** if the leads sub-menu structure has changed, follow the current convention rather than forcing a separate item — could be an "..." overflow with "Import" inside, or an inline header button on `/user/leads`. Adapt at edit time.

## Rollback

Delete the new files. Revert the routes + sidebar edits. Backend state (imports table) is untouched.
