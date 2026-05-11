# Step 5.10 — AI Virtual Staging — frontend

**Goal:** AI Recommend page matching the screenshot. Upload base room, upload furniture items, prompt, generate, preview.
**Phase:** 5
**Depends on:** 5.9
**Status:** Pending

## Scope
**In-scope:**
- `app/src/app/features/user/packs/furniture/virtual-staging/`:
  - `staging-api.service.ts`
  - `staging.page.ts/.html` — left: base + furniture uploads + prompt; right: jobs list with status pills + result thumbnails.
  - `result-detail.component.ts/.html` — full preview + download.
- WS subscription updates job statuses live.
- Tailwind only.

## Files to touch
- `app/src/app/features/user/packs/furniture/virtual-staging/*` (created)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. File picker with previews; chip list for furniture pieces.
2. Generate button submits multipart; new job appears in jobs list as `queued`.
3. WS handler updates job statuses without polling.
4. Result thumbnail click → detail view + download.

## Verification checklist
**Frontend:**
- visit `/virtual-staging` → page renders.
- generate → job pill flips queued → running → done.
- preview shows the rendered image.

## Self-check (10 rules)
- [ ] Tailwind only.

## Stop & report
Await "proceed" before Step 5.11.
