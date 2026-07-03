# Step 5 — Property backend: public endpoints + Fernet token

**Goal:** Ship the two unauthenticated public endpoints — `GET /api/public/properties` (grid of published listings) and `GET /api/public/property/{token}` (single property detail via encrypted opaque token). Introduce a Property-domain Fernet helper (`link_token.py`) that hides the property UUID behind a symmetric-encrypted, URL-safe token so the public URL never leaks internal IDs.

**Track:** Real Estate CRM Pack
**Status:** Pending
**Depends on:** Steps 2–4 (Property models + CRUD + images).

---

## Scope

**IN:**

1. `link_token.py` — new file at `api/src/app/packs/real_estate/modules/property/link_token.py`:
   ```python
   from cryptography.fernet import Fernet, InvalidToken
   from src.app.core.config import settings

   _fernet = Fernet(settings.PROPERTY_LINK_ENCRYPTION_KEY.encode())

   def encode_property_token(property_id: UUID, org_id: UUID) -> str:
       payload = f"{property_id}|{org_id}".encode()
       return _fernet.encrypt(payload).decode()

   def decode_property_token(token: str) -> tuple[UUID, UUID] | None:
       try:
           decrypted = _fernet.decrypt(token.encode()).decode()
           pid_str, oid_str = decrypted.split("|", 1)
           return UUID(pid_str), UUID(oid_str)
       except (InvalidToken, ValueError):
           return None
   ```
   - Token embeds both `property_id` and `org_id` (org_id needed to hit the RLS-scoped session for fetch).
   - Symmetric Fernet: encrypt/decrypt with one key; tamper → `InvalidToken` → return `None` → caller returns 404.
   - No expiry in v1 (Fernet supports `ttl` — add later if product wants time-limited listings).

2. `settings.py` (backend config) — add `PROPERTY_LINK_ENCRYPTION_KEY: str` field. Read from env. Add to [API/secrets.enc.env](../../API/secrets.enc.env) via `run secrets-edit` (SOPS-encrypted). Generate a fresh Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

3. `service.py` — add:
   - `generate_public_link(db, *, org_id, actor_user_id, property_id, host: str) -> str`:
     - Fetch property; verify status == `published` (only published properties get shareable links); return the encoded URL: `f"{host}/property/{token}"`.
     - Permission: `property.read`.
   - `list_public_properties(db, *, org_id) -> list[PublicPropertyCardOut]`:
     - Fetch all properties with `status='published'` for the org, eager-load featured image only.
     - Return trimmed public shape: title, price, city, property_type, short description (first 200 chars), featured image URL.
   - `get_public_property(db, *, token) -> PublicPropertyDetailOut | None`:
     - Call `decode_property_token(token)`; if `None` → return `None` → router 404.
     - Set RLS context to the decoded `org_id` (via existing `with_org_context(org_id)` helper — or the pattern the app uses for org-scoped background jobs).
     - Fetch property by id; verify `status == 'published'`. If not, return `None` (don't leak draft/archived existence).
     - Return full public shape: all viewer-safe fields + full image gallery ordered by `display_order`.

4. `schemas.py` — add:
   - `PublicPropertyCardOut` — trimmed card shape for grid (id-less: never expose UUID).
   - `PublicPropertyDetailOut` — full detail shape (title, description, price, currency, address fields, bedrooms/bathrooms/area, amenities, contact person + phone + email, images ordered).
   - `PublicUrlOut` — `{ url: str }`.

5. `router.py` — add authenticated endpoint:
   - `POST /api/v1/property/{id}/public-url` — returns `{ url }`. Permission: `property.read`.

6. `public_router.py` — **new file** for the unauth endpoints. Mount separately under `/api/public/*`:
   - `GET /api/public/properties?org={slug}` — grid of published for the org identified by `slug` (looked up in `tbl_organizations`). No auth.
   - `GET /api/public/property/{token}` — single property detail. No auth. 404 on bad token, non-published, or wrong org.
   - Both endpoints marked `include_in_schema=True` in Swagger (visible to devs).

   The `?org=<slug>` query parameter on the list endpoint is v1's answer to "which org's listings?" — v2 could switch to per-org subdomains (`realestatedemo.crm.example.com/properties`). Decision recorded here so we don't accidentally silo v1 to a single-tenant assumption.

7. **Rate limiting** — public endpoints get a lax IP-based rate limit (60 req / 5 min per IP) via the existing rate-limiter middleware (check `core/rate_limit/` for the pattern; if not present, note it as a follow-up rather than adding a new middleware in this step).

8. Router mount in `main.py`.

9. Pytest — `test_public_endpoints.py`:
   - Generate a public URL for a published property → decoding round-trips to the same property_id.
   - Fetch `/api/public/property/{token}` — returns detail.
   - Fetch with a tampered token (flip one char) → 404.
   - Fetch with a token for a draft property → 404.
   - Fetch with a token for an archived property → 404.
   - `GET /api/public/properties?org=<slug>` returns only published for that org.
   - `GET /api/public/properties?org=<slug>` from a different org's slug does not leak this org's listings.

**OUT:**

- No frontend public pages — Step 9.
- No SEO meta tag rendering — Step 9 covers it in the Angular public route.
- No token expiry / signed short links. v1 is unbounded (public listings stay public until unpublished). Product to decide if TTL is needed.

## Files touched

| File | Change |
|---|---|
| `api/src/app/packs/real_estate/modules/property/link_token.py` | New (~35 lines). |
| `api/src/app/packs/real_estate/modules/property/public_router.py` | New (~90 lines). |
| `api/src/app/packs/real_estate/modules/property/service.py` | Modify — add ~110 lines. |
| `api/src/app/packs/real_estate/modules/property/router.py` | Modify — add ~25 lines (the authenticated `POST .../public-url`). |
| `api/src/app/packs/real_estate/modules/property/schemas.py` | Modify — add ~50 lines. |
| `api/src/app/core/config.py` | Modify — add `PROPERTY_LINK_ENCRYPTION_KEY` setting. |
| `api/secrets.enc.env` | Modify via `run secrets-edit` — add the generated Fernet key. |
| `api/src/app/main.py` | Modify — 1 line to mount `public_router`. |
| `api/tests/packs/real_estate/test_public_endpoints.py` | New (~180 lines). |

**9 files, ~490 lines.** Within Rule 8.

## Verification checklist

- [ ] Generate a Fernet key locally, save via `run secrets-edit`.
- [ ] Backend starts without errors.
- [ ] Create + publish a property; call `POST /api/v1/property/{id}/public-url` → returns a URL like `https://host/property/gAAAAAB...`.
- [ ] Hit `GET /api/public/property/gAAAAAB...` from an incognito browser (no JWT) → returns full detail JSON.
- [ ] Change one char in the token → 404.
- [ ] Unpublish the property; fetch same URL → 404 (existence hidden).
- [ ] `GET /api/public/properties?org=<demo_org_slug>` returns the grid.
- [ ] `uv run pytest tests/packs/real_estate/test_public_endpoints.py -v` — 7 assertions green.

## Raw SQL to paste after install

None. Key lives in secrets.enc.env; no schema changes.

## Self-check against the 10 rules

- **Rule 1** — Public endpoint lives in the pack module, not `core/`; router mounted in `main.py` (allowed).
- **Rule 2** — Public read enforces `status == 'published'` filter + org-scoped fetch; the Fernet token binds both property_id and org_id so RLS remains authoritative.
- **Rule 5** — No sidebar entry for public routes (they're not modules).
- **Layering** — `public_router.py` calls `service.py`; service touches DAL; no CRUD in router. Pin-test remains green.
- **Security** —
  - Fernet: symmetric + HMAC — tamper detection is intrinsic.
  - No property IDs leak; no org IDs leak (except via the `?org=<slug>` public listing lookup which is opt-in).
  - Non-published properties return the same 404 as invalid tokens — no side-channel leak of existence.
  - Rate limiting handles abuse (or documented as follow-up).

## Stop and report

- **Files changed:** 9 files.
- **What you can verify:** curl the public endpoints from an incognito context, tamper-test the token, confirm 404 semantics, pytest.
- **Tests added:** 7 assertions.
- **Self-check:** 10-rule + security block.
- **Awaiting 'proceed'** — Step 6 starts the frontend shell for the Property module (owner dashboard list page).
