# Real Estate CRM Pack — Track

A focused track that ships the **Real Estate CRM stack** as a fully-active vertical pack (Layer 2), on par with the Furniture pack that already exists. The centerpiece is a new **Property** module — create/edit/publish/archive property listings with multi-image galleries and share them via public, tokenized URLs that never expose internal IDs.

Sits outside the numbered phase tree — vertical-specific, ship-when-ready. Builds directly on top of the shipped `onboarding-setup/` and `phase-4-furniture-pack/` scaffolding.

## Why this exists

The pack architecture is production-ready:

- [core/packs/catalog_config.py](../../API/src/app/core/packs/catalog_config.py) lists Real Estate as a "Coming soon" placeholder tile with `template_id: "real_estate"`, `default_currency: "INR"`, `modules_preview: ["listings", "site_visits", "channel_partners", "brokerage"]`.
- [core/module_registry.py](../../API/src/app/core/module_registry.py) walks `packs/*/modules/*/module.py` at startup — no core changes needed to add a pack; drop the files and they self-register.
- [packs/furniture/](../../API/src/app/packs/furniture/) already proves the shape: `pack.yaml` + 7 modules with the full layered structure (`models.py` / `schemas.py` / `router.py` / `service.py` / `data_access.py` / `module.py`).
- Every stack automatically ships the full **Core CRM** underneath (contacts, leads, pipelines, activities, tasks, appointments, conversations, campaigns, workflows, billing, reporting, ...) — pack modules are additive, never a replacement.

The gap is that no `packs/real_estate/` folder exists on disk, and the Property module described in the requirements doc has never been written. This track closes that gap.

| Gap | What's missing today |
|---|---|
| **Real Estate tile is inactive** | Onboarding shows it as "Coming soon", disabled in UI, rejected by backend. |
| **No `packs/real_estate/` folder** | No `pack.yaml`, no installer target, no modules — a new org can't pick this vertical because there's nothing to install. |
| **No Property module** | The domain-primary entity (property listings) has no models, routes, or UI anywhere in the repo. |
| **No public property URLs** | The requirements need `/properties` (list) and `/property/{token}` (detail) with encrypted tokens — neither route nor helper exists. |
| **No multi-image property gallery** | Existing image helpers cover single-image uploads (catalog covers); a property-images gallery table + reorder/featured endpoints don't exist yet. |

## What this does NOT do (preserved invariants)

- Does **not** change the auth core, JWT handling, or onboarding flow. `onboarding-setup/` is shipped and untouched.
- Does **not** modify [core/module_registry.py](../../API/src/app/core/module_registry.py), permission registry, RLS policy loader, or sidebar resolver. Pack modules self-register via the existing walker.
- Does **not** modify the Furniture pack or any core module. Real Estate is purely additive.
- Does **not** replace the Core CRM modules — every Real Estate org still gets contacts/leads/pipelines/activities/tasks/conversations/campaigns/workflows/etc. via the standard core registry.
- Does **not** introduce raw AES. Uses the existing Fernet helper pattern from [core/integrations/crypto.py](../../API/src/app/core/integrations/crypto.py) with a new domain key `PROPERTY_LINK_ENCRYPTION_KEY`. Symmetric, opaque, URL-safe, rotate-ready.
- Does **not** ship Site Visits, Channel Partners, or Brokerage modules in this track. Those are Real Estate pack Phase-2 work (parallel to `phase-6-furniture-pack-features/`). Track scope is **Property module only** — the flagship vertical-specific module that makes Real Estate CRM real.
- Does **not** add S3 or cloud storage. Filesystem-only via [shared/storage/base.py](../../API/src/app/shared/storage/base.py) per the locked stack.
- Does **not** modify `Flutter/` or `/admin/**` or `/staff-portal/**`.

## Acceptance criteria

A new visitor:

1. Registers, hits `/onboarding`, sees a **selectable "Real Estate CRM" tile** (not "Coming soon").
2. Picks Real Estate + names their org + submits → lands in `/user/dashboard` on a fully-seeded org: Real Estate pipelines, roles, custom fields, currency, defaults — plus the entire Core CRM sidebar (contacts, leads, pipelines, etc.).
3. Sees a new **"Properties"** sidebar entry (permission-gated by `property.*` keys).
4. From `/user/properties`, can:
   - Create a new property with all fields per the requirements (title, type, category, price, address, city/state/country/pincode, bedrooms, bathrooms, area, amenities, contact person, phone, email, description).
   - Upload multiple images (drag-select, reorder, pick featured).
   - Edit, delete, publish, unpublish, archive.
   - Filter by status (My / Draft / Published / Archived / Sold).
   - Search by title/city/type.
   - Copy the public URL to clipboard.
   - Preview the public listing in a new tab.
5. Anyone (no login) can visit `https://<host>/properties` and see the grid of published listings for that org's public listings (org-scoped via subdomain or query param — see Step 9). Each card: featured image, title, price, location, type, short description, "View Details" link.
6. Anyone can visit `https://<host>/property/{encryptedToken}` and see the full property detail page. Draft / archived / deleted / unpublished properties return 404. Tampered tokens return 404.
7. The URL never contains a raw property UUID or numeric ID.

All without any DB-level intervention, CLI installer step, or engineering assistance.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Real Estate pack manifest + activate onboarding tile](step-1-pack-manifest-activation.md) | Pending | ~½ day |
| 2 | [Property backend: models, migration, RLS, DAL](step-2-property-models-dal.md) | Pending | ~1 day |
| 3 | [Property backend: service, router, module descriptor (CRUD)](step-3-property-service-router.md) | Pending | ~1 day |
| 4 | [Property backend: multi-image gallery (upload, delete, reorder, featured)](step-4-property-images.md) | Pending | ~1 day |
| 5 | [Property backend: public endpoints + Fernet token](step-5-public-endpoints-token.md) | Pending | ~½ day |
| 6 | [Property frontend: shell + list page + owner tabs](step-6-frontend-list-shell.md) | Pending | ~1 day |
| 7 | [Property frontend: create/edit form + image gallery UI](step-7-frontend-form-gallery.md) | Pending | ~1 day |
| 8 | [Property frontend: actions (publish, archive, delete, copy URL, preview)](step-8-frontend-actions.md) | Pending | ~½ day |
| 9 | [Public listing page + public detail page (no-auth routes)](step-9-public-pages.md) | Pending | ~1 day |
| 10 | [Real Estate pack smoke test + demo seed](step-10-smoke-and-seed.md) | Pending | ~½ day |

**Total: ~8 working days.** Each step independently verifiable in under 30 minutes; stop-and-report after every step per rule 9.

## Dependencies

- `onboarding-setup/` track — **Done.** Steps 1–5 shipped. The Real Estate tile flips from "Coming soon" → selectable via a single line change in [catalog_config.py](../../API/src/app/core/packs/catalog_config.py); the onboarding page picks it up with zero code changes.
- `phase-4-furniture-pack/` scaffolding — **Done.** The pack manifest schema, `installer.py` contract, and module-registry walker are all live and battle-tested by the Furniture pack.
- Fernet crypto helper — **Done.** [core/integrations/crypto.py](../../API/src/app/core/integrations/crypto.py) already provides `encrypt` / `decrypt` under `INTEGRATIONS_ENCRYPTION_KEY`. Step 5 introduces a parallel domain key `PROPERTY_LINK_ENCRYPTION_KEY` reusing the same helper pattern.
- Image validation — **Done.** [shared/files/image.py](../../API/src/app/shared/files/image.py) enforces 5 MB max, JPEG/PNG/WebP whitelist, magic-byte validation.
- Storage backend — **Done.** [shared/storage/base.py](../../API/src/app/shared/storage/base.py) + [shared/storage/local.py](../../API/src/app/shared/storage/local.py) provide `put` / `url` at `./storage/{org_id}/{entity}/{file_id}`.

No new external dependencies. No new Python packages (Fernet is via `cryptography`, already installed).

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| Backend pack manifest (Step 1) | ~3 new + 1 modified | `packs/real_estate/__init__.py`, `packs/real_estate/pack.yaml`, `packs/real_estate/modules/__init__.py`; modify `core/packs/catalog_config.py`. |
| Property module backend (Steps 2–5) | ~10 new + Alembic migration | `packs/real_estate/modules/property/{__init__, models, schemas, router, service, data_access, module}.py` + `link_token.py` helper + `constants.py`; 1 Alembic migration file. |
| Property module frontend (Steps 6–8) | ~10 new + ~2 modified | `app/features/user/packs/real_estate/property/` (list, form, gallery, actions, service, types, routes) + sidebar wiring. |
| Public pages (Step 9) | ~5 new + ~2 modified | `app/features/public/properties/` (listing + detail + service) + top-level route wiring outside `/user`. |
| Tests (per step) | ~3 backend pytest files + 1 frontend spec | Per-step minimal coverage. |
| Demo seed + smoke (Step 10) | ~2 new + 1 seed SQL | `packs/real_estate/seed_demo.py` + a raw INSERT SQL block in the step report. |

**Total ~35 files across 10 steps.** Each step ≤ 10 files / ≤ 400 lines per rule 8.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Rule 1 — `/core` never imports `/packs` | Pack module discovered by the existing walker in `core/module_registry.py`; no core file names `real_estate`. |
| Rule 2 — Every table has `org_id` + `tbl_` prefix | `tbl_rp_properties` and `tbl_rp_property_images` both carry `org_id UUID NOT NULL`, RLS policies filter on it. `rp_` prefix marks Real-Estate-Pack ownership analogous to Furniture's `fp_`. |
| Rule 3 — Custom fields layered model | Property carries a `custom_data JSONB` column; org-level property custom fields register with `source='pack'` in `custom_field_definitions` via the pack manifest. |
| Rule 4 — Dynamic form rendering | Property create/edit form queries `GET /api/{entity}/fields?entity_type=property` and renders standard + custom fields dynamically — no hardcoded form field arrays. |
| Rule 5 — Sidebar registry | Property module exports `ModuleDescriptor` at `packs/real_estate/modules/property/module.py`; sidebar auto-picks it up. |
| Rule 6 — Permission registry | `property.read`, `property.write`, `property.publish`, `property.archive`, `property.delete` registered by the module descriptor; roles in `pack.yaml` grant `property.*`. |
| Rule 7 — Pack manifest is source of truth | `packs/real_estate/pack.yaml` seeds pipelines, roles, custom fields, defaults; the installer is untouched. |
| Rule 8 — Step size | Each step ≤ 10 files, verifiable in < 30 min. |
| Rule 9 — Stop and report | Explicit stop template at the bottom of each step file. |
| Rule 10 — Production ready | No TODOs, no commented-out code, no "fix later". Every step leaves the tree clean. |

## Backend layered architecture (self-check)

Per manager spec 2026-06-25 (recorded in memory):
- `models.py`, `schemas.py`, `router.py`, `service.py`, `data_access.py` split — Property module conforms.
- Only `service.py` calls `db.commit / rollback / refresh / flush`.
- `router.py` never runs SQL; only resolves deps, calls service, returns response.
- `data_access.py` runs pure CRUD, no transactions, no business logic.
- Public-endpoint router in Step 5 conforms to the same rules — no shortcuts because it's unauthenticated.

## Public URL scheme (Step 5 + 9 recap)

```
Owner clicks "Copy Public URL"
   ↓
Frontend calls  POST /api/v1/property/{id}/public-url
   ↓
Backend:  Fernet.encrypt(property.id + timestamp) → opaque URL-safe token
   ↓
Response: { "url": "https://<host>/property/eyJ0eXAi..." }
   ↓
Public visitor loads /property/eyJ0eXAi...
   ↓
Backend:  Fernet.decrypt(token) → property.id
   ↓
Fetch property WHERE id = ... AND status = 'published' AND org_id = ...
   ↓
Return property detail  OR  404 if not found / draft / archived / tampered token
```

**Token properties:**
- Opaque — no property ID or org ID visible in the URL.
- Signed — Fernet HMACs the payload; any tamper → decrypt raises `InvalidToken` → 404.
- Symmetric — one key rotates all tokens (`PROPERTY_LINK_ENCRYPTION_KEY`, stored in SOPS-encrypted [API/secrets.enc.env](../../API/secrets.enc.env)).
- Not expiring in v1 — Fernet supports TTL; add a `max_age_seconds` parameter later if link expiry becomes a product requirement.

## After this track

- The CRM ships **two live vertical stacks** — a real-estate business owner and a furniture retailer can both self-serve at signup.
- **Real Estate pack Phase 2** work (Site Visits, Channel Partners, Brokerage, RERA compliance) can proceed in parallel with core Phase 5 hardening — infrastructure is done.
- The multi-image gallery pattern (Step 4) is generalizable: any future entity needing a photo gallery (Furniture custom-order photos, field-ops site photos, contact avatars-plus-gallery) can reuse the same DAL/service shape.
- The Fernet public-token pattern (Step 5) is reusable for any future "shareable public link" — quotes, invoices, deal one-pagers — with a per-domain key.
- Adding the next vertical (Healthcare, Automotive, Education, ...) becomes: mirror this track, swap the pack manifest and the primary domain module. No onboarding, sidebar, permissions, or crypto changes needed.

## When to start

Whenever the user says "proceed on Step 1." No currently-active track blocks this one. The work is real, the pattern is proven, the placeholder is already in the catalog waiting to be flipped.
