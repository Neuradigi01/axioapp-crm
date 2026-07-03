# Step 9 — Public listing page + public detail page (no-auth routes)

**Goal:** Ship the two public-facing Angular routes — `/properties?org=<slug>` (grid of published listings) and `/property/{token}` (single property detail). No login required; no sidebar; no user chrome; SEO-friendly meta tags.

**Track:** Real Estate CRM Pack
**Status:** COMPLETED
**Depends on:** Step 5 (public backend endpoints).

---

## Scope

**IN:**

1. Scaffold a new top-level public feature folder:
   ```
   app/src/app/features/public/
   ├── public.routes.ts
   ├── property-listing/
   │   ├── property-listing.component.ts
   │   ├── property-listing.component.html
   │   └── property-listing.component.scss
   ├── property-detail/
   │   ├── property-detail.component.ts
   │   ├── property-detail.component.html
   │   └── property-detail.component.scss
   └── shared/
       ├── public-property-api.service.ts
       └── public-shell.component.ts   (minimal header + footer wrapper — no sidebar)
   ```

2. Wire into `app.routes.ts` at the top level (not under `/user`, not under `/accounts`):
   ```ts
   {
     path: '',
     loadChildren: () => import('./features/public/public.routes').then(m => m.PUBLIC_ROUTES),
   }
   ```
   `public.routes.ts` exposes:
   - `path: 'properties'` → PropertyListingComponent.
   - `path: 'property/:token'` → PropertyDetailComponent.

   Route ordering matters — these must resolve before the `/user/**` and `/accounts/**` catchalls. Confirm during implementation.

3. `public-property-api.service.ts` — standalone, uses `HttpClient` **without** the auth interceptor (public endpoints). Adds no Authorization header:
   - `listPublic(orgSlug): Observable<PublicPropertyCard[]>`
   - `getByToken(token): Observable<PublicPropertyDetail>`

4. `property-listing.component.ts`:
   - Reads `org` from query string (`?org=demo-real-estate`).
   - If missing → error page ("Please use the shareable link provided by the property owner").
   - Fetches grid via API.
   - Renders:
     - Simple header bar (org name + "Properties" title).
     - Responsive grid (3-col desktop, 1-col mobile).
     - Each card: featured image (lazy-loaded), title, price + currency, city + state, property_type badge, short description (first 200 chars), "View Details" button linking to the property's public token URL (backend returns `public_url` on each card so we don't have to encode client-side).
   - Empty state: "No properties listed yet."
   - Basic search (client-side filter by title/city).
   - No login/logout affordances (this is the pure public surface).

5. `property-detail.component.ts`:
   - Reads `:token` route param.
   - Fetches via `getByToken(token)`.
   - On 404 → renders friendly "Property not available" page with home link (no leak of "was this ever a property? did we unpublish? did you tamper?").
   - Layout:
     - Hero: image carousel of all gallery images (featured first), navigation dots + arrows.
     - Below: title, price, city+state, property_type badge, category.
     - Details grid: bedrooms, bathrooms, area, address (formatted multi-line).
     - Amenities section (chip list).
     - Description (long-form).
     - Contact card: contact_person, phone (`tel:` link), email (`mailto:` link).
     - Optional: "Send enquiry" form (client-side stub in v1 — full lead-capture wiring is out of scope; button links to a mailto with pre-filled subject `Enquiry: {{title}}` for v1).
   - Mobile-first responsive.

6. **SEO meta tags** — use Angular's `Meta` service:
   - `<title>` = property title + " – " + org name.
   - `<meta name="description">` = first 160 chars of description.
   - `<meta property="og:image">` = featured image URL.
   - `<meta property="og:title">` = property title.
   - `<meta property="og:type">` = "product" (real-estate schema.org type is best but "product" is safe).
   - No structured JSON-LD in v1 (deferred to Real Estate Phase 2 SEO track).

7. **`public-shell.component.ts`** — minimal wrapper: transparent top nav with just the org name (or "Properties" branding), no sidebar, no user chrome, no dashboard links. All public routes render inside this shell.

8. **No auth interceptor** — the public-api service should either construct a bare HttpClient without auth interceptor OR the interceptor should skip requests whose URL starts with `/api/public/`. Check the existing interceptor logic (likely already has a whitelist pattern for public endpoints — grep `public` in `features/accounts/shared/interceptors/`). Add if missing.

9. **Prettier + eslint** clean on all new files.

**OUT:**

- Server-side rendering (SSR). Angular Universal not in the locked stack for this project. SEO meta tags via `Meta` service work at CSR-load time; Google can still index dynamic content.
- Enquiry form → CRM lead creation. v1 uses `mailto:` — full integration with the lead-capture track is a follow-up.
- Analytics tracking (Plausible / GA). Deferred.
- Multi-tenant subdomain routing. v1 uses `?org=<slug>` query param.

## Files touched

| File | Change |
|---|---|
| `app/features/public/public.routes.ts` | New. |
| `app/features/public/property-listing/property-listing.component.ts` | New (~180 lines). |
| `app/features/public/property-listing/property-listing.component.html` | New (~120 lines). |
| `app/features/public/property-detail/property-detail.component.ts` | New (~200 lines). |
| `app/features/public/property-detail/property-detail.component.html` | New (~180 lines). |
| `app/features/public/shared/public-property-api.service.ts` | New (~60 lines). |
| `app/features/public/shared/public-shell.component.ts` | New (~50 lines). |
| `app/src/app/app.routes.ts` | Modify — add public route stanza. |
| Auth interceptor | Modify (if needed) — skip `/api/public/*` URLs. |

**~9 files, ~800 lines.** At the upper edge of Rule 8. If it grows, split into 9a (listing) and 9b (detail) — natural boundary.

## Verification checklist

- [ ] Open incognito browser → visit `http://localhost:4200/properties?org=demo-real-estate` → grid renders with published properties.
- [ ] Click a card → detail page loads at `/property/{token}`.
- [ ] URL contains an opaque Fernet token, no numeric ID.
- [ ] Copy URL, unpublish the property, reload → "Property not available" page.
- [ ] Change one char in the token → "Property not available".
- [ ] View source → SEO meta tags present with real content.
- [ ] Mobile viewport → single-column layout works.
- [ ] No auth prompts, no redirect to login.
- [ ] Auth interceptor confirmed skipping the public URLs (network tab: no Authorization header).
- [ ] Existing user flow (`/user/*` and `/accounts/*`) still works — no route collision.

## Self-check against the 10 rules

- **Rule 1** — Public pages live in `features/public/`, not in `features/user/packs/real_estate/`. They serve any pack that publishes shareable links (future Furniture or Automotive listings could reuse — but v1 is Property-specific). Placement decision: public listing pages that are inherently vertical-specific *could* live under the pack; but since Fernet tokens are agnostic to entity type and Real Estate Property is the only entity today, placing it at `features/public/` keeps the URL surface at the app root cleanly. Confirm placement at step start.
- **Rule 4** — Detail page renders custom fields dynamically if the property has custom_data (loop through custom_field_definitions).
- **Rule 10** — Enquiry `mailto:` is a real link, not a stub. Full lead-capture integration is deferred but v1 works end-to-end.

## Stop and report

- **Files changed:** 9 files.
- **What you can verify:** incognito browser test of both public routes, view-source SEO check, tamper-token 404, mobile viewport.
- **Tests added:** 2 frontend specs (listing renders grid, detail 404 on bad token).
- **Self-check:** 10-rule + SEO + auth-interceptor block.
- **Awaiting 'proceed'** — Step 10 seeds demo data and runs the end-to-end smoke test.
