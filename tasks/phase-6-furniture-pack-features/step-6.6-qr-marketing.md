# Step 6.6 — In-Store QR Marketing — backend + frontend

**Goal:** `fp_qr_campaigns`, `fp_qr_scans` tables. QR code generation. Stats per campaign. UI matching the Store Marketing tab in staff dashboard.
**Phase:** 6 — Furniture Pack Features
**Depends on:** 1.6, 3.4
**Status:** Pending

## Scope
**In-scope:**
- Backend:
  - `QrCampaign` (`fp_qr_campaigns`, TenantScoped): id, org_id, name, slug (unique per org), redirect_url, kind (sale/feedback/menu/etc.), is_active, created_at.
  - `QrScan` (`fp_qr_scans`, TenantScoped): id, org_id, campaign_id, scanned_at, ip, ua, location_hint.
  - Migration + RLS.
  - Public route `GET /qr/{org_slug}/{campaign_slug}` — records scan, redirects to redirect_url.
  - Admin endpoints: `/qr-campaigns` CRUD, `/qr-campaigns/{id}/png` (returns PNG QR code), `/qr-campaigns/{id}/stats`.
  - Permission: `qr.read`, `qr.write`.
- Frontend:
  - `app/src/app/features/user/packs/furniture/qr-marketing/` — page with campaigns list, create/edit, download PNG, stats chart.
  - Wire into Staff dashboard "Store Marketing" tab (3.5) — replace stub.

## Files to touch
- `api/src/app/packs/furniture/modules/qr_marketing/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0028_fp_qr.py` (created)
- `app/src/app/features/user/packs/furniture/qr-marketing/*` (created)
- `app/src/app/features/user/core/staff/tabs/store-marketing.component.ts/.html` (modified — replaces stub)

## Plan
1. Backend: `qrcode` Python lib (already in deps from existing 2FA) for PNG.
2. Public scan route: rate limit per IP (light), records scan asynchronously, redirects.
3. Frontend list with create modal (name, kind, redirect_url, slug).

## Tests to add
- `tests/test_qr_scan.py` — scan increments count.

## Verification checklist
**Backend:**
- create campaign → PNG download works.
- visit `/qr/demo/spring-sale` → 302 to redirect; scan recorded.
**Frontend:**
- staff dashboard Store Marketing tab → live.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] Public scan route does NOT require auth but is org-scoped via slug.

## Stop & report
Await "proceed" before Step 5.7.
