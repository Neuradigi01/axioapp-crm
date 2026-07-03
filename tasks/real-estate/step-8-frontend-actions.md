# Step 8 — Property frontend: row + toolbar actions

**Goal:** Wire the action buttons on the list rows and the property detail toolbar — Publish, Unpublish, Archive, Mark Sold, Delete, Edit, Copy Public URL, Preview Public.

**Track:** Real Estate CRM Pack
**Status:** Pending
**Depends on:** Steps 3, 5, 6, 7.

---

## Scope

**IN:**

1. **Row action menu** (per-property in the list table):
   - Uses a lightweight menu popover (mirror the pattern from an existing list page — grep `features/user/core/contacts/list/` for `dropdown` or `menu` styling).
   - Actions vary by `status`:
     - `draft` → Edit, Publish (needs ≥1 image), Delete.
     - `published` → Edit, Unpublish, Archive, Mark Sold, Copy Public URL, Preview.
     - `unpublished` → Edit, Publish, Archive, Delete.
     - `archived` → Edit (view-only), no state actions; option to Unarchive → back to draft.
     - `sold` → Edit (view-only), no state actions.
   - Confirmation modal for Delete + Archive (destructive).
   - Toast (success/error) via existing MatSnackBar or Tailwind toast pattern the app uses.

2. **Toolbar** (on the create/edit page from Step 7):
   - Same actions as row menu, exposed as inline buttons on the sticky footer.

3. `PropertyApiService` — endpoints already stubbed in Step 6; ensure all are implemented:
   - `publish(id)`, `unpublish(id)`, `archive(id)`, `unarchive(id)` (dispatches `PATCH` with `status="draft"`), `markSold(id)`, `remove(id)`, `generatePublicUrl(id)`.

4. **Copy Public URL** flow:
   - Call `POST /api/v1/property/{id}/public-url` → response `{ url: "https://.../property/{token}" }`.
   - `navigator.clipboard.writeText(url)` → toast "Public URL copied to clipboard".
   - If clipboard API blocked (older browsers / permissions): modal with the URL in a read-only text box and a Copy button.

5. **Preview Public** flow:
   - Same endpoint → open `url` in `window.open(url, "_blank", "noopener")`.

6. **Publish precondition** — frontend disables Publish button and shows tooltip "Add at least one image to publish" when `image_urls.length === 0`. Server also enforces (Step 3 service check); this is UX.

7. **Optimistic UI** for status toggles — the row's status badge updates immediately, list re-fetches in the background to confirm. On error, revert + toast.

8. Prettier + eslint clean.

**OUT:**

- Public pages themselves — Step 9.
- Bulk actions (select multiple, bulk archive) — not in v1.

## Files touched

| File | Change |
|---|---|
| `app/features/user/packs/real_estate/property/list/property-list.component.ts` | Modify — add action handlers, dropdown state. |
| `app/features/user/packs/real_estate/property/list/property-list.component.html` | Modify — replace placeholder actions cell with real menu. |
| `app/features/user/packs/real_estate/property/form/property-form.component.ts` | Modify — add toolbar actions. |
| `app/features/user/packs/real_estate/property/form/property-form.component.html` | Modify — add toolbar buttons. |
| `app/features/user/packs/real_estate/property/shared/property-api.service.ts` | Modify — verify all endpoints wired (may already be from Step 6). |
| `app/features/user/packs/real_estate/property/shared/confirm-dialog/confirm-dialog.component.ts` (if not extracted already) | New or reuse the shared confirm dialog from `features/user/core/shared/`. |

**~6 files, ~350 lines.** Within Rule 8.

## Verification checklist

- [ ] Row menu opens on click, closes on outside-click.
- [ ] Publish disabled for a property with 0 images; tooltip explains.
- [ ] Publish on a property with images → status flips to Published (row updates, tab counts update).
- [ ] Unpublish, Archive, Mark Sold — each transitions correctly and shows toast.
- [ ] Delete → confirm modal → deletion → row disappears → tab counts update.
- [ ] Copy Public URL → toast "Copied"; paste in a new tab → public detail loads (Step 9 must be done for this; if Step 8 ships first, the toast still works but the URL 404s until Step 9 lands).
- [ ] Preview Public → new tab opens with the public detail URL.
- [ ] All API failures show error toast; optimistic changes revert.
- [ ] Permission gating — a role without `property.publish` sees the Publish button disabled with a lock icon (existing pattern used elsewhere).
- [ ] eslint + prettier clean.

## Self-check against the 10 rules

- **Rule 6** — Client-side permission gating uses the granted-permissions signal already provided by auth service. Backend re-checks — client cannot bypass.
- **Rule 10** — All buttons wired to real endpoints; no `console.log("todo: publish")` stubs.

## Stop and report

- **Files changed:** 6 files.
- **What you can verify:** full lifecycle walk-through — create → publish → copy URL → preview (once Step 9 lands) → unpublish → archive → delete.
- **Tests added:** 1 spec covering the action-menu open/close + permission-gate visibility.
- **Self-check:** 10-rule block + accessibility (menu keyboard-navigable).
- **Awaiting 'proceed'** — Step 9 ships the public-facing pages (`/properties` grid + `/property/{token}` detail).
