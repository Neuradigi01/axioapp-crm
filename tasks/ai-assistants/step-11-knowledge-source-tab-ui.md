# Step 11 — Knowledge Source tab UI

**Goal:** Ship the Knowledge Source tab UI. Three sub-tabs / segments: **Upload File**, **Custom Data**, **URL**. Sources list below with status pill + progress bar + vector-id + updated timestamp + Delete / Cancel / Replace actions. Match existing pages visually — no new patterns.
**Status:** COMPLETED
**Depends on:** Step 10 (backend endpoints).

---

## Scope

In-scope:

- `editor/tabs/knowledge-source-tab.component.ts/.html` — flesh out from Step 7 placeholder:
  - **Source type segmented control** at top (3 pills): Upload File · Custom Data · URL. Selecting one shows the corresponding input widget.
  - **Upload File** panel:
    - Drop zone card matching Pabbly screenshot: dashed border, cloud-upload icon, text "Choose a file or drag it here." Help text: "Size < 90MB, Accepted formats: .txt (Preferred) or .pdf (No page limit for text PDFs, but if the PDF has images, it's limited to 10 pages)."
    - On drop / select — validate client-side (size + extension), then POST `multipart/form-data` to `/ai-assistants/{id}/knowledge/file`.
    - Progress indicator during upload (0–100% XHR upload progress).
    - On success, add row to sources list; on 4xx (dedup returned existing) show info banner "This file is already in your knowledge base".
  - **Custom Data** panel:
    - Title input (optional, default "Untitled").
    - Textarea (10 rows, resizable) with placeholder "Paste your custom content here (FAQs, product info, policies, etc.)".
    - Character counter + "Add to Knowledge" button.
    - POST to `/ai-assistants/{id}/knowledge/text`.
  - **URL** panel:
    - URL input with `type="url"`.
    - Title input (optional).
    - "Add URL" button.
    - POST to `/ai-assistants/{id}/knowledge/url`.
    - Standard amber warning banner: "URLs pointing to private or internal addresses will be rejected."
  - **Knowledge Sources list** (below the input panels):
    - Table-like layout matching the Pabbly screenshot: columns `Source / Last Updated`, `Name / Vector ID`, `Status`, `Actions`.
    - Row per source: icon by source_type, name (or original_filename or URL), truncated vector_id (first 8 chars), status pill (grey/amber/green/red per status), progress bar during `processing` with percentage.
    - Actions: **Cancel** button visible only when `status='processing'`; **Replace** button visible on `ready`; **Delete** button always; each with a confirm dialog.
    - Empty state: "No knowledge sources yet. Add one above to teach your assistant."
    - Polling: while any row is `processing` or `pending`, poll `GET /ai-assistants/{id}/knowledge` every 3s until all rows terminal.
  - **Replace flow** — Replace button opens a modal identical to Upload with an alert: "Uploading a new file will replace the existing knowledge and any current chat sessions will start using the new content."
- API service edits: `getKnowledge(assistantId)`, `uploadFile`, `addText`, `addUrl`, `cancelKnowledge`, `deleteKnowledge`, `replaceKnowledge`.
- Types matching Step 10's schemas.

Out of scope:
- Backend (Step 10 covers).
- Analytics / retrieval-quality metrics (deferred).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge-source-tab.component.ts` | **EDIT** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge-source-tab.component.html` | **EDIT** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/upload-file-panel.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/upload-file-panel.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/custom-data-panel.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/custom-data-panel.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/url-panel.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/url-panel.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/sources-list.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/sources-list.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/replace-modal.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge/replace-modal.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/ai-assistants-api.service.ts` | **EDIT** — add knowledge endpoints |

**~13 files. ~600 lines.** Sub-components extracted to keep each file under 100 lines.

## Plan

1. Segmented control matches existing pattern (grep for `segment` / `tab-pills` in other tabs).
2. Upload panel uses XHR with progress event (Angular `HttpClient.request` with `reportProgress: true`).
3. Sources list polls only while rows are in flight; when all terminal, stops polling.
4. Replace modal explicitly warns; user must confirm.
5. Standard amber banner reused per `feedback_standard_warning_banner_pattern`.
6. All lucide icons (`upload-cloud`, `file-text`, `link`, `x`, `trash-2`, `refresh-cw`) verified against `app.config.ts`.
7. Prettier on all touched files.

## DB changes / migrations

None.

## Tests

Angular component tests:
- Segmented control switches panel.
- File drop triggers upload with progress.
- Duplicate upload shows info banner.
- Custom-data Save posts and appends row.
- URL panel Save posts.
- Sources list polls while a row is `processing`; stops on terminal.
- Cancel button visible only when processing.
- Replace modal shows warning; on confirm calls replace endpoint.
- Delete confirm dialog.

## Smoke

```
1. Open Knowledge Source tab. Segmented control shows 3 pills.
2. Upload a small PDF. Progress bar 0→100. Row appears, status pending→processing→ready.
3. Add custom data "Test entry". Row appears, ingests quickly, ready.
4. Add URL http://example.com. Row appears.
5. Add same PDF again — info banner appears, no duplicate row.
6. Delete a row — confirm — row disappears.
7. Trigger a long ingest (large PDF); click Cancel; row status flips to failed_ingest.
```

## Risks

- Client-side size cap (90MB) must match backend cap; drift will show a bad UX.
- Polling every 3s during ingest is fine at low scale; for orgs with many concurrent ingests consider a single-consolidated poll (out of v1 scope).

## Self-check (10 rules)

`APP/` frontend only. ✓ N/A org_id. N/A custom fields / dynamic forms / sidebar. ✓ Permission at API. ✓ pack.yaml untouched. ✓ 13 files / ~600 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 11 — Knowledge Source tab UI
Files: 13
Verify: all 3 source types work end-to-end; dedup shows info banner; sources list
        polls and stops; cancel/delete/replace confirmed.
Tests: ~10 Angular component tests.
Awaiting "proceed".
```
