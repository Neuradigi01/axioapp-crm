# Step 26 — QR code generator + wa.me short links with tracking

**Goal:** Offline-to-online conversion: generate QR codes (for storefronts / billboards / receipts) and short wa.me tracking links. Each link tracks clicks/scans + attributes resulting conversations.
**Status:** Pending
**Depends on:** Step 24 (attribution column infrastructure).

---

## Scope

In-scope:
- Table `tbl_whatsapp_quick_contact_links` (org-scoped, RLS): id, org_id, code (short slug), phone_number_id, prefilled_message TEXT, label (internal), created_by_user_id, created_at, click_count, scan_count.
- Service generates short URL `https://app.core-crm.com/wa/{code}` 302-redirecting to `https://wa.me/{phone}?text={urlencode(prefilled)}`.
- Click tracker logs to `tbl_whatsapp_quick_contact_clicks` (anonymized: UA family, region, referrer, recorded_at).
- Attribution: when a customer messages the WA number with matching prefilled body within a fingerprint window (e.g. 10 min), attribute the conversation to the link (updates Step 24's columns).
- QR generation: server-side render (Python `qrcode` lib) → PNG / SVG endpoint.
- Endpoints:
  - `GET /api/v1/whatsapp/quick-links` (paginated)
  - `POST /api/v1/whatsapp/quick-links`
  - `PATCH /api/v1/whatsapp/quick-links/{id}`
  - `DELETE /api/v1/whatsapp/quick-links/{id}`
  - `GET /api/v1/whatsapp/quick-links/{id}/qr.png?size=512`
  - `GET /api/v1/whatsapp/quick-links/{id}/stats`
- Public 302 endpoint `/wa/{code}` (no auth; rate-limited).
- Frontend `/user/whatsapp/quick-links` (or under Settings → WhatsApp).
- Download QR as PNG / SVG / printable PDF.
- Stats: link clicks + QR scans + attributed conversations.

Out of scope:
- Multi-number routing in QR — Step 27.
- Geographic targeting based on scan location — defer.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/quick_links.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/models.py` | Two new tables |
| `API/alembic/versions/<ts>_quick_contact_links.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/router.py` | CRUD endpoints |
| `API/src/app/core/integrations/whatsapp/qr_generator.py` | **NEW** PNG/SVG render |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Match prefilled body within window → attribute |
| `API/src/app/main.py` (or public router) | Public `/wa/{code}` redirect |
| `APP/.../whatsapp/quick-links/quick-links-page.component.ts` | **NEW** |
| `APP/.../whatsapp/quick-links/quick-link-editor.component.ts` | **NEW** |
| `APP/.../whatsapp/quick-links/qr-download.component.ts` | **NEW** |
| `API/tests/integrations/test_quick_links.py` | **NEW** |

**~11 files. ~600 lines.**

## Plan

1. Migration: two tables + slug-uniqueness check.
2. Slug generator: 8-char base62; collision retry.
3. Click recorder: lightweight (insert + counter increment); async to avoid latency.
4. QR endpoint: PIL / qrcode lib; size param 256/512/1024.
5. Match-on-inbound: hash prefilled body; lookup recent (10-min) clicks with same fingerprint; attribute conversation.
6. Public 302: rate-limited per IP to prevent abuse.
7. Tests cover: slug gen, redirect, attribution match, QR render.

## DB changes / migrations

Two new tables + indexes.

## Tests

8 pytest + 2 Jest.

## Smoke

```
1. Create link "Mall billboard" → phone Neuradigi WA, prefilled "I saw your billboard".
2. Download QR PNG 512px. Confirm scans open WhatsApp pre-filled.
3. Visit https://app.core-crm.com/wa/<code> → 302 → wa.me opens.
4. Click count + scan count increment.
5. Send the prefilled message → new conversation attribution shows link source.
6. Stats page shows clicks / scans / attributed convs.
7. Delete link → 404 on the public URL.
```

## Risks

- Public endpoint abuse — IP-based rate limit + slug entropy.
- Prefilled body modified by user breaks attribution — accept; attribution best-effort.
- QR for large messages: WhatsApp truncates; warn UI if > 200 chars.

## Self-check (10 rules)

`core/integrations/whatsapp/` + small public main route. ✓ Rule 1. New tables org_id + RLS (public endpoint deliberately bypasses RLS via service-key marker, like data-deletion in Step 4). ✓ Rule 2 with documented exception. No custom-field changes. ✓. Static UI. ✓ N/A. New sub-page. ✓. `whatsapp.automation.manage` reuse. ✓ Rule 6. pack.yaml untouched. ✓. 11 files / ~600 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 26 — QR + wa.me links
Files: 11
Verify: QR scan / link click / attribution / stats.
Tests: 8 pytest + 2 Jest.
Next: Step 27 — multi-number per org.
Awaiting "proceed".
```
