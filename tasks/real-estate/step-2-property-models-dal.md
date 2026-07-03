# Step 2 — Property backend: models, migration, RLS, DAL

**Goal:** Create the two Property tables (`tbl_rp_properties`, `tbl_rp_property_images`) with `org_id`, RLS policies, all fields per the requirements doc, plus the module folder skeleton and a pure-CRUD `data_access.py`.

**Track:** Real Estate CRM Pack
**Status:** COMPLETED
**Depends on:** Step 1 (pack manifest active).

---

## Scope

**IN:**

1. Scaffold the Property module folder:
   ```
   api/src/app/packs/real_estate/modules/property/
   ├── __init__.py
   ├── models.py           ← this step
   ├── schemas.py          ← this step (skeleton)
   ├── data_access.py      ← this step
   ├── constants.py        ← this step (enums)
   └── (module.py, router.py, service.py come in Step 3)
   ```

2. `constants.py` — enums for the schema:
   - `PropertyStatus`: `draft`, `published`, `unpublished`, `archived`, `sold`.
   - `PropertyType`: `apartment`, `villa`, `plot`, `commercial_office`, `commercial_shop`, `warehouse`, `farmhouse`, `pg_hostel`, `other`.
   - `PropertyCategory`: `residential_sale`, `residential_rent`, `commercial_sale`, `commercial_rent`, `land_sale`.

3. `models.py` — SQLAlchemy 2.x async ORM only. Two tables:

   **`tbl_rp_properties`** (all columns typed with `Mapped[...]`):
   - `id: UUID (PK, default uuid4)`
   - `org_id: UUID (FK organizations.id, NOT NULL, indexed)`
   - `owner_id: UUID (FK users.id, NOT NULL, indexed)` — creator/owner within the org
   - `title: str (NOT NULL, len 3..200)`
   - `slug: str (NOT NULL, unique per org, len ≤ 220)` — machine-generated from title on insert; used by internal analytics, not by public URL (Fernet token owns public routing per Step 5)
   - `description: str | None (TEXT)`
   - `property_type: str (NOT NULL)` — validated against `PropertyType` enum at service layer
   - `category: str (NOT NULL)` — validated against `PropertyCategory` enum
   - `price: Decimal(14,2) | None`
   - `currency: str(3)` (default from org settings)
   - `address_line: str | None (len ≤ 500)`
   - `city: str | None (len ≤ 100, indexed)`
   - `state: str | None (len ≤ 100)`
   - `country: str | None (len ≤ 100)`
   - `pincode: str | None (len ≤ 20)`
   - `bedrooms: int | None`
   - `bathrooms: int | None`
   - `area_value: Decimal(10,2) | None`
   - `area_unit: str(20) | None` — sqft / sqm / acres / cents / gaj
   - `amenities: list[str]` (JSONB, default `[]`) — free-form tag list; UI multi-select
   - `contact_person: str | None (len ≤ 200)`
   - `contact_phone: str | None (len ≤ 40)`
   - `contact_email: str | None (len ≤ 200)`
   - `status: str (NOT NULL, default "draft", indexed)` — one of `PropertyStatus`
   - `published_at: datetime | None`
   - `archived_at: datetime | None`
   - `sold_at: datetime | None`
   - `custom_data: dict (JSONB, default `{}`)` — org custom fields per Rule 3
   - `created_at: datetime (NOT NULL, default now())`
   - `updated_at: datetime (NOT NULL, default now(), onupdate=now())`
   - Indexes:
     - `ix_rp_properties_org_status_created` on `(org_id, status, created_at DESC)`
     - `ix_rp_properties_org_city_type` on `(org_id, city, property_type)` — filter combo
     - `uq_rp_properties_org_slug` UNIQUE `(org_id, slug)`
     - GIN on `amenities` — for tag-array filtering later.

   **`tbl_rp_property_images`**:
   - `id: UUID (PK)`
   - `org_id: UUID (FK, NOT NULL, indexed)` — denormalized for RLS
   - `property_id: UUID (FK tbl_rp_properties.id ON DELETE CASCADE, NOT NULL, indexed)`
   - `image_path: str (NOT NULL, len ≤ 500)` — relative path under `./storage/{org_id}/property/{property_id}/`
   - `image_url: str | None (len ≤ 500)` — cached public URL (resolved via `StorageBackend.url`)
   - `content_type: str(50)` — jpeg / png / webp
   - `size_bytes: int`
   - `display_order: int (NOT NULL, default 0, indexed)`
   - `is_featured: bool (NOT NULL, default False)`
   - `created_at: datetime`
   - Indexes: `ix_rp_property_images_property_order` on `(property_id, display_order)`.
   - Partial unique index: `uq_rp_property_images_featured` UNIQUE `(property_id)` WHERE `is_featured = True` — enforces at-most-one featured image per property.

4. Alembic migration — `alembic/versions/xxxx_property_tables.py`:
   - `op.create_table("tbl_rp_properties", ...)` + `op.create_table("tbl_rp_property_images", ...)`.
   - Enable RLS on both tables:
     ```sql
     ALTER TABLE tbl_rp_properties ENABLE ROW LEVEL SECURITY;
     CREATE POLICY tbl_rp_properties_isolation ON tbl_rp_properties
       USING (org_id = current_setting('app.current_org_id')::uuid);
     ```
   - Same policy for `tbl_rp_property_images`.
   - `downgrade()` drops policies then tables in reverse order.

5. `schemas.py` — skeleton with 3 Pydantic v2 models:
   - `PropertyBase` (all optional-safe editable fields).
   - `PropertyOut` (adds `id, org_id, owner_id, status, published_at, archived_at, sold_at, created_at, updated_at, image_urls: list[str]`, `featured_image_url: str | None`).
   - `PropertyImageOut` (id, image_url, display_order, is_featured).
   - Request models come in Steps 3–4.

6. `data_access.py` — pure CRUD (Rule: DAL never touches transactions):
   - `insert_property(db, *, org_id, owner_id, data) -> Property`
   - `get_property_by_id(db, *, org_id, property_id) -> Property | None`
   - `list_properties(db, *, org_id, filters, page, page_size) -> tuple[list[Property], int]`
   - `update_property(db, *, property, data) -> Property`
   - `delete_property(db, *, property) -> None`
   - `insert_property_image(db, *, org_id, property_id, image_data) -> PropertyImage`
   - `list_property_images(db, *, property_id) -> list[PropertyImage]`
   - `update_property_image(db, *, image, data) -> PropertyImage`
   - `delete_property_image(db, *, image) -> None`
   - `unset_featured_for_property(db, *, property_id) -> None` (bulk update: set `is_featured=False` for all images of a property; called by service before setting a new featured).
   - `count_properties_by_status(db, *, org_id, owner_id) -> dict[str, int]` — for the owner-dashboard tab badges.
   - No `db.commit / flush / refresh / rollback`. Uses `db.add`, `db.delete`, `db.execute(select/update/delete)`.

7. Pytest — `api/tests/packs/real_estate/test_property_dal.py`:
   - Insert a property; read it back; assert fields.
   - RLS smoke: set `app.current_org_id` to org A, query — see A's rows; switch to org B — see B's rows only.
   - Featured-image uniqueness: try to insert two `is_featured=True` for one property → partial unique index rejects the second.

**OUT:**

- No router or service — Step 3.
- No image upload endpoint or actual file bytes handling — Step 4.
- No public endpoints — Step 5.

## Files touched

| File | Change |
|---|---|
| `api/src/app/packs/real_estate/modules/property/__init__.py` | New (empty). |
| `api/src/app/packs/real_estate/modules/property/constants.py` | New (~40 lines). |
| `api/src/app/packs/real_estate/modules/property/models.py` | New (~180 lines). |
| `api/src/app/packs/real_estate/modules/property/schemas.py` | New skeleton (~50 lines). |
| `api/src/app/packs/real_estate/modules/property/data_access.py` | New (~200 lines). |
| `api/alembic/versions/xxxx_property_tables.py` | New (~120 lines with RLS). |
| `api/tests/packs/real_estate/__init__.py` | New (empty). |
| `api/tests/packs/real_estate/test_property_dal.py` | New (~150 lines). |

**8 files, ~740 lines total** — but ~180 is models, ~200 is DAL, ~150 is tests, ~120 is migration. Verifiable end-to-end (models → migration → up/down → DAL smoke tests) in under 30 min.

If the total feels tight against Rule 8's 400-line soft cap: the migration file is largely auto-generated Alembic scaffolding, models are declarative column definitions, and DAL is 10 short pure functions. Content density is low. Splitting further into Step 2a (models + migration) and Step 2b (DAL + tests) is a valid alternative — decide when this step is picked up.

## Verification checklist

- [ ] `alembic upgrade head` runs cleanly against a fresh test DB.
- [ ] `alembic downgrade -1` reverses cleanly (drop policies, drop tables).
- [ ] `alembic upgrade head` again — idempotent.
- [ ] RLS pin-test: query `tbl_rp_properties` as org A → only A rows. Switch `app.current_org_id` → only B rows.
- [ ] `uv run pytest tests/packs/real_estate/test_property_dal.py -v` — green.
- [ ] Existing `test_table_name_convention.py` — still green (our new tables use `tbl_rp_` prefix which matches the `tbl_` rule).
- [ ] Existing `test_layered_architecture_convention.py` — still green (no CRUD calls outside DAL, no transactions in DAL).

## Raw SQL to paste after install

```sql
-- Sample debug queries (report only)
SELECT id, title, status, published_at FROM tbl_rp_properties WHERE org_id = '<org_uuid>' ORDER BY created_at DESC LIMIT 20;
SELECT property_id, is_featured, display_order FROM tbl_rp_property_images WHERE property_id = '<property_uuid>' ORDER BY display_order;
```

Migration itself uses Alembic `op.execute()` for the RLS policies — no manual SQL needed post-install.

## Self-check against the 10 rules

- **Rule 2** — Both tables carry `org_id` and `tbl_rp_` prefix; RLS policies are in the migration; index on `(org_id, ...)` composite for query efficiency.
- **Rule 3** — `custom_data JSONB` column on `tbl_rp_properties` supports the layered custom-fields model.
- **Rule 8** — Step is verifiable end-to-end in under 30 min.
- **Layering** — `data_access.py` uses only `db.add / delete / execute` — no `commit / flush / refresh / rollback`. Enforced by the pin-test.
- **DB efficiency** — Composite indexes for the two hot filter paths (`org_id + status + created_at`, `org_id + city + type`); GIN on amenities for tag search.

## Stop and report

- **Files changed:** 8 files above.
- **What you can verify:** run migration up/down, inspect `\d tbl_rp_properties` in psql, run the DAL pytest.
- **Tests added:** `test_property_dal.py` — 6 assertions covering insert, read, list, update, delete, RLS isolation.
- **Self-check:** 10-rule block.
- **Awaiting 'proceed'** — Step 3 wires up the service, router, and module descriptor for the full CRUD API surface.
