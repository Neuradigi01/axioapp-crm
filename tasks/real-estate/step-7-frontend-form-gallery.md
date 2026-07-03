# Step 7 — Property frontend: create/edit form + image gallery UI

**Goal:** Ship the property create/edit form (all fields per the requirements) and the multi-image gallery uploader (drag-select, drag-reorder, pick featured, delete).

**Track:** Real Estate CRM Pack
**Status:** Pending
**Depends on:** Steps 4, 6 (backend image endpoints + frontend shell).

---

## Scope

**IN:**

1. Scaffold the form folder:
   ```
   app/features/user/packs/real_estate/property/form/
   ├── property-form.component.ts
   ├── property-form.component.html
   └── property-form.component.scss
   ```

2. Scaffold the gallery folder:
   ```
   app/features/user/packs/real_estate/property/gallery/
   ├── property-gallery.component.ts
   ├── property-gallery.component.html
   └── property-gallery.component.scss
   ```

3. `property-form.component.ts`:
   - Standalone, uses **typed reactive forms** (Rule: Angular 20+ locked stack) — `FormGroup<PropertyFormControls>`.
   - Detects create vs edit from route param `:id`.
   - On edit: loads via `PropertyApiService.getById(id)`, hydrates the form.
   - Sections (each a card):
     - **Basics**: title (required), property_type (select: Apartment/Villa/Plot/Commercial-Office/Commercial-Shop/Warehouse/Farmhouse/PG-Hostel/Other), category (select: Residential-Sale/Rent, Commercial-Sale/Rent, Land-Sale), price + currency, description.
     - **Location**: address_line (textarea), city, state, country, pincode.
     - **Property details**: bedrooms, bathrooms, area_value + area_unit (sqft/sqm/acres/cents/gaj), amenities (chip multi-select — free-form typing, comma-separated tags; store `list[str]`).
     - **Contact**: contact_person, contact_phone (with basic client-side validation via existing phone-input pattern if present), contact_email.
     - **Custom fields** — render dynamically from `GET /api/v1/custom-fields/render?entity_type=property`. Follows the shipped custom-fields engine (per Rule 4). Grep `features/user/core/shared/dynamic-form/` for the pattern.
     - **Images**: embeds `<property-gallery [propertyId]="propertyId()" [readonly]="isCreate()">` — enabled only after the property exists (create flow: save-as-draft first, then show gallery).
   - Submit: on create → POST → redirect to `:id/edit` so the user can add images. On edit → PATCH → toast "Saved".
   - Validation errors surfaced inline (existing zinc error style).
   - Sticky footer with `Cancel` (back to list) and `Save` primary button.

4. `property-gallery.component.ts`:
   - Standalone.
   - `@Input() propertyId: Signal<string>` (or `input.required<string>()` per Angular 20 pattern).
   - Load images on init via `list-images` endpoint (or extend `PropertyApiService.getById` to return them; either works — pick the pattern used by contacts avatar / catalog images and mirror).
   - **Upload panel**: drag-and-drop zone + hidden file input; accepts multiple files. On drop:
     - Client-side validate (type + size 5 MB) before POST.
     - Multipart upload to `POST /api/v1/property/{id}/images`.
     - On response, refresh the gallery.
   - **Gallery grid**: 4-column responsive grid. Each cell:
     - Thumbnail (object-cover, aspect-square).
     - Featured badge (yellow "★ Featured") if `is_featured`.
     - Hover overlay with two buttons: `Set featured` (if not already) and `Delete`.
     - Drag handle (uses the Angular CDK drag-drop primitives — already installed if used elsewhere; check `package.json`).
   - **Reorder**: `cdkDropList` fires on drop → collect new order → PATCH `/reorder`.
   - Delete confirmation modal (small — "Delete this image? This cannot be undone.")
   - Empty state: "No images uploaded yet. Drag files here or click to browse."

5. Amenities chip input — pick an existing chip/tag input pattern used elsewhere in the app (grep `features/user/core/` for `chip` or `tag`). If none exists, a minimal Tailwind implementation: text input + on-enter/comma adds to list; each chip has an × to remove. Aim for <60 lines.

6. Dynamic custom-fields rendering — reuse the existing `<dynamic-fields entity_type="property" [(ngModel)]="customData">` component. Confirm at step start that the property entity type is wired into the custom-fields registry (should be, as `pack.yaml` from Step 1 declares custom fields for it). If not wired, add the tag to the entity_type enum whitelist.

7. Prettier — run on all new files before commit.

**OUT:**

- Row/toolbar actions (publish, archive, delete, copy URL) — Step 8.
- Public pages — Step 9.
- Image cropping / rotation / bulk-caption. Not in v1.

## Files touched

| File | Change |
|---|---|
| `app/features/user/packs/real_estate/property/form/property-form.component.ts` | New (~250 lines). |
| `app/features/user/packs/real_estate/property/form/property-form.component.html` | New (~200 lines). |
| `app/features/user/packs/real_estate/property/form/property-form.component.scss` | New (thin). |
| `app/features/user/packs/real_estate/property/gallery/property-gallery.component.ts` | New (~200 lines). |
| `app/features/user/packs/real_estate/property/gallery/property-gallery.component.html` | New (~120 lines). |
| `app/features/user/packs/real_estate/property/gallery/property-gallery.component.scss` | New (thin). |
| `app/features/user/packs/real_estate/property/shared/property-api.service.ts` | Modify — add image endpoints (upload, delete, reorder, set-featured). |
| `app/features/user/packs/real_estate/property/shared/property.types.ts` | Modify — add form-shape types. |

**8 files, ~800 lines.** At the upper edge of Rule 8; consider a 7a/7b split (form vs gallery) if the form portion balloons beyond 400 lines during implementation.

## Verification checklist

- [ ] Click "New Property" → form loads on `/user/properties/new`.
- [ ] Required fields (title, property_type, category) block submit.
- [ ] Submit valid form → property created (status=draft) → redirect to `/user/properties/{id}/edit`.
- [ ] Gallery panel becomes active — drag 3 JPEGs in → upload progress → thumbnails render.
- [ ] Drag-reorder — persists across refresh.
- [ ] Set featured on 2nd image — badge moves; refresh confirms.
- [ ] Delete an image — confirm modal → deletion → gallery updates.
- [ ] Uploading a 6 MB file → client-side rejects with friendly toast.
- [ ] Uploading an SVG → client-side rejects.
- [ ] Custom fields declared in `pack.yaml` render as extra inputs in the form.
- [ ] Save existing property → PATCH → toast.
- [ ] Prettier + eslint clean.

## Self-check against the 10 rules

- **Rule 4** — Form combines static schema fields (typed reactive form) with dynamic custom fields (rendered from `/custom-fields/render`). No hardcoded custom-field arrays.
- **Rule 8** — At the edge; split into 7a/7b if it grows.
- **Rule 10** — Every button wired; no placeholders; no TODOs.

## Stop and report

- **Files changed:** 8 files.
- **What you can verify:** full create → save → upload images → reorder → set featured → refresh → verify persistence.
- **Tests added:** 2 frontend specs (form validation smoke + gallery reorder smoke).
- **Self-check:** 10-rule block + Angular typed forms + dynamic fields + Tailwind + prettier.
- **Awaiting 'proceed'** — Step 8 wires the row + toolbar action buttons (publish, unpublish, archive, delete, copy URL, preview).
