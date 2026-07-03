# Step 6 — Property frontend: shell + list page + owner tabs

**Goal:** Wire the frontend Property module into `/user/properties` with the owner dashboard shell — sidebar entry auto-registered from Step 3's module descriptor, list page with tabs (My / Draft / Published / Archived / Sold), search bar, pagination, per-row action menu placeholders.

**Track:** Real Estate CRM Pack
**Status:** Pending
**Depends on:** Steps 3–5 (backend Property CRUD + images + public endpoints).

---

## Scope

**IN:**

1. Scaffold the frontend feature folder:
   ```
   app/src/app/features/user/packs/real_estate/property/
   ├── property.routes.ts
   ├── list/
   │   ├── property-list.component.ts
   │   ├── property-list.component.html
   │   └── property-list.component.scss
   ├── shared/
   │   ├── property-api.service.ts
   │   └── property.types.ts
   ```

2. `property.types.ts` — mirror backend schemas:
   - `Property` (matches `PropertyOut`).
   - `PropertyImage`.
   - `PropertyListFilters`.
   - `PropertyListResponse` (envelope).
   - `PropertyStatus` string union: `'draft' | 'published' | 'unpublished' | 'archived' | 'sold'`.

3. `property-api.service.ts` — standalone injectable, uses `HttpClient` + the retry-on-transient-failure interceptor (per memory: default for new HTTP work):
   - `list(filters, page, pageSize): Observable<PropertyListResponse>`
   - `getById(id): Observable<Property>` — for later steps.
   - `create(payload): Observable<Property>` — for Step 7.
   - `update(id, patch): Observable<Property>` — for Step 7.
   - `remove(id): Observable<void>` — for Step 8.
   - `publish(id) / unpublish(id) / archive(id) / markSold(id)` — for Step 8.
   - `generatePublicUrl(id): Observable<{ url: string }>` — for Step 8.

4. `property-list.component.ts` — standalone (per Angular 20+ locked stack):
   - Angular signals for state: `filters`, `page`, `pageSize`, `list` (via `toSignal`), `statusCounts` (derived), `loading`, `error`.
   - Tab bar: `All | Draft | Published | Unpublished | Archived | Sold`, each with count badge from `status_counts`.
   - Search input (debounced 300ms) → updates `filters.search` → refetches.
   - Filter panel: city, property_type dropdown, price range slider — collapsed by default; expand to reveal.
   - Pagination bar (per-page-size selector, page arrows).
   - Table columns: featured thumb (24×24 rounded), title (+ slug muted below), status badge, price (formatted with org currency), city, updated_at (relative "3 days ago"), actions cell (placeholder button "•••" for Step 8).
   - Empty state: "No properties yet. Click 'New Property' to add your first listing." + primary CTA button.
   - Header: page title "Properties" + primary CTA "New Property" (opens Step 7's form; placeholder route in this step).

5. `property-list.component.html` — Tailwind only (per CLAUDE.md rule for new UI). Zinc palette. Cards, tabs, table follow the existing user-app conventions (grep for similar list pages under `features/user/core/contacts/` for reference).

6. `property.routes.ts` — Angular routes:
   ```ts
   export const PROPERTY_ROUTES: Routes = [
     { path: '', component: PropertyListComponent },
     { path: 'new', loadComponent: () => import('./form/property-form.component').then(m => m.PropertyFormComponent) },  // Step 7
     { path: ':id/edit', loadComponent: () => import('./form/property-form.component').then(m => m.PropertyFormComponent) },  // Step 7
   ];
   ```

7. Wire into `user.routes.ts` (or wherever the pack routes are stitched — grep for `packs/furniture` route wiring to find the exact spot):
   ```ts
   {
     path: 'properties',
     loadChildren: () => import('./packs/real_estate/property/property.routes').then(m => m.PROPERTY_ROUTES),
   }
   ```
   The sidebar auto-renders "Properties" via the module descriptor from Step 3 — no explicit sidebar edit needed.

8. Lucide icon registration — add `home`, `plus`, `search`, `filter`, `more-vertical`, `image-off` to `app.config.ts` if not already present. Per memory: missing icons throw mid-render.

9. Prettier — after writing, run `npx --no-install prettier --write <paths>` on the new files. Per memory: pre-commit bounces otherwise.

**OUT:**

- No create/edit form — Step 7.
- No row actions (publish, delete, copy URL) — Step 8. Actions column shows a disabled placeholder button.
- No public pages — Step 9.

## Files touched

| File | Change |
|---|---|
| `app/src/app/features/user/packs/real_estate/property/property.routes.ts` | New. |
| `app/src/app/features/user/packs/real_estate/property/list/property-list.component.ts` | New (~180 lines). |
| `app/src/app/features/user/packs/real_estate/property/list/property-list.component.html` | New (~150 lines). |
| `app/src/app/features/user/packs/real_estate/property/list/property-list.component.scss` | New (thin — mostly Tailwind). |
| `app/src/app/features/user/packs/real_estate/property/shared/property-api.service.ts` | New (~100 lines). |
| `app/src/app/features/user/packs/real_estate/property/shared/property.types.ts` | New (~60 lines). |
| `app/src/app/features/user/user.routes.ts` (or the pack routes stitch file) | Modify — add 1 route entry. |
| `app/src/app/app.config.ts` | Modify — register any missing lucide icons. |

**8 files, ~500 lines.** Within Rule 8. All Tailwind, no PrimeNG / Material introductions.

## Verification checklist

- [ ] Log in as an org on the Real Estate pack (create one via onboarding if needed).
- [ ] Sidebar shows "Properties" entry with `home` icon (auto-registered from module descriptor).
- [ ] Click → routes to `/user/properties` → list page renders.
- [ ] Empty state shows "No properties yet."
- [ ] After creating one via Swagger (Step 3 endpoint), refresh → property appears in the list with correct status badge, thumbnail placeholder, price.
- [ ] Tab bar updates counts.
- [ ] Search debounces + refetches.
- [ ] Pagination arrows work.
- [ ] No console errors, no missing-icon exceptions.
- [ ] `npx eslint` + `prettier --check` — clean.

## Self-check against the 10 rules

- **Rule 4** — Form rendering is dynamic — this step doesn't render a form, but the list page does render custom-field-driven columns if the org has property-level custom fields. Actual dynamic-form rendering lands in Step 7.
- **Rule 5** — Sidebar entry via module descriptor; no sidebar file edit.
- **Rule 10** — No placeholders in shipped state. The "actions" button is disabled with a tooltip "Coming in next step" — but only during this WIP step; Step 8 wires it up before merge.

  Note: per Rule 10, we don't merge a UI with a stub button. If Step 6 needs to ship independently of Step 8, invert: hide the actions column entirely in Step 6, add it whole in Step 8. Confirm approach at step start.

## Stop and report

- **Files changed:** 8 files.
- **What you can verify:** log in, click Properties in sidebar, see empty state, create via Swagger, refresh, see list.
- **Tests added:** 1 frontend spec (`property-list.component.spec.ts`) — smoke test that the component compiles and renders empty state.
- **Self-check:** 10-rule block + Angular signals + Tailwind + prettier verified.
- **Awaiting 'proceed'** — Step 7 wires the create/edit form + image gallery uploader.
