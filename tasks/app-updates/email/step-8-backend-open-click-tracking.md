# Step 8 — Backend: open pixel + link rewriting + delivery state

**Goal:** Per-send tracking: a 1×1 tracking pixel injected into outbound HTML records opens. Outbound links are rewritten through a redirector to record clicks. Both update per-message + per-template + per-sequence stats. Compliance: `List-Unsubscribe` headers + unsubscribe link footer.
**Track:** App Updates → Email
**Status:** Pending
**Depends on:** Step 5 (send pipeline), Step 6 (templates), Step 7 (sequences).

---

## Scope

In-scope:

- Alembic migration adding `email_message_opens` + `email_message_clicks` tables.
- `core/email/tracking/` sub-package:
  - `pixel.py` — inject `<img src="{TRACKING_BASE}/o/{token}" width="1" height="1">` at the bottom of outbound `body_html`.
  - `link_rewriter.py` — find every `<a href="…">` in `body_html`, replace with `{TRACKING_BASE}/c/{token}?u={base64url(href)}`. Skip `mailto:`, `tel:`, and existing tracking URLs.
  - `router.py` — public endpoints:
    - `GET /api/v1/track/o/{token}` — return 1×1 transparent GIF, record open.
    - `GET /api/v1/track/c/{token}?u=…` — 302 to the decoded URL, record click.
    - `GET /api/v1/track/unsubscribe/{token}` — unsubscribe landing page (HTML).
- Token format: HMAC-signed JWT-lite `{message_id, kind: 'open' | 'click' | 'unsub'}`. Short signing key from env. No PII in URL.
- Modify Step 5 adapter `send` pipeline to call pixel + link rewriter on `body_html` before MIME assembly. Insert `List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers.
- Bottom-of-email footer: auto-append `Unsubscribe` link + sender's company name + physical address (from `org.settings.company_address`). CAN-SPAM + Indian DPDP compliance.
- Unsubscribe handling: a click sets `contacts.email_opt_out=true`. Future sends to that contact: adapter returns `OptedOut` and any active sequence enrollment for them auto-cancels.

Out of scope:

- Bounce processing — the providers handle bounces in their own UI; we surface what they report via the sync (already in Steps 2/3) but don't build a full bounce-management UI.
- Per-link UTM injection — leave for marketing.

## Tables

```sql
CREATE TABLE email_message_opens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id),
    message_id  UUID NOT NULL REFERENCES messages(id),
    opened_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_hash     TEXT,                                  -- sha256(ip)[:16]
    user_agent_hash TEXT
);

CREATE INDEX email_opens_message_idx ON email_message_opens (message_id, opened_at);

CREATE TABLE email_message_clicks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id),
    message_id  UUID NOT NULL REFERENCES messages(id),
    target_url  TEXT NOT NULL,
    clicked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_hash     TEXT
);

CREATE INDEX email_clicks_message_idx ON email_message_clicks (message_id, clicked_at);

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS email_opt_out BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS email_opt_out_at TIMESTAMPTZ;

-- RLS on both new tables
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_email_tracking.py` | created |
| `api/src/app/core/email/tracking/__init__.py` | created |
| `api/src/app/core/email/tracking/pixel.py` | created |
| `api/src/app/core/email/tracking/link_rewriter.py` | created |
| `api/src/app/core/email/tracking/router.py` | created |
| `api/src/app/core/email/tracking/tokens.py` | created — HMAC encode/decode |
| `api/src/app/core/conversations/channels/email_adapter.py` | modified — call pixel + link rewriter + opt-out check |
| `.env.example` | modified — add `TRACKING_BASE_URL`, `TRACKING_HMAC_KEY` |
| `api/src/app/main.py` | modified — include tracking router (public, no auth) |
| `api/tests/test_email_tracking.py` | created |

**10 files, 1 migration.** At rule-8 ceiling.

## Plan

1. `tokens.py`: `encode({message_id, kind}) -> str` (urlsafe base64 of `payload + '.' + hmac_sha256(payload)`), `decode(token) -> dict | None`. Reject tampered.
2. `pixel.py`: BeautifulSoup4 the HTML (already in `pyproject`?  if not, add it). Append `<img>` just before `</body>` or at end if no body tag.
3. `link_rewriter.py`: walk every `<a href>` in BS4. Skip `mailto:` / `tel:` / data URIs / our own tracking URLs (idempotency). Rewrite to `{base}/c/{token}?u={b64(href)}`.
4. Router:
   - `/o/{token}`: decode; if valid, insert `email_message_opens` (best-effort — duplicate opens are fine, no dedup). Return 1×1 GIF with `Cache-Control: no-store`.
   - `/c/{token}?u=…`: decode token; decode `u`; insert `email_message_clicks`. 302 to the URL. If decode fails or `u` is missing → 404.
   - `/unsubscribe/{token}`: decode; set contact `email_opt_out=true`, `email_opt_out_at=now`. Cancel any active sequence enrollments for that contact. Show a simple "You've been unsubscribed" page.
5. Adapter wiring: in `send`, just before MIME assembly:
   - Check `contact.email_opt_out` → raise `OptedOut` (router returns 451).
   - Call `pixel.inject(body_html, message_id)`.
   - Call `link_rewriter.rewrite(body_html, message_id)`.
   - Append footer with unsubscribe link.
   - Set `List-Unsubscribe: <mailto:unsubscribe@…>, <{base}/unsubscribe/{token}>` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` MIME headers.

## Tests

`api/tests/test_email_tracking.py`:

- **Token roundtrip:** encode/decode preserves payload; tampered token rejected.
- **Pixel injection:** body_html with and without `</body>` both get the pixel correctly placed.
- **Link rewriter:** `<a href="https://x.com">` → `<a href="{base}/c/{token}?u=…">`. mailto + tel skipped. Already-tracked URLs untouched.
- **Open recording:** GET pixel URL → row inserted. Multiple GETs → multiple rows (no dedup).
- **Click recording + redirect:** GET click URL → 302 to original URL; row inserted.
- **Tampered token rejected:** modify a char → 404.
- **Unsubscribe:** GET unsubscribe URL → contact.email_opt_out=true; active sequence enrollments for that contact cancelled.
- **Opt-out blocks send:** seed opted-out contact; adapter.send → OptedOut raised.
- **List-Unsubscribe headers present:** sent MIME contains both headers.
- **Open from Gmail image-proxy:** simulate Gmail proxy UA → still recorded (proxy effect documented).

## Smoke

```powershell
docker exec template_api-api-1 uv run alembic upgrade head
docker exec template_api-api-1 uv run pytest tests/test_email_tracking.py -v

# Public endpoints (no auth):
curl -i http://localhost:8000/api/v1/track/o/<valid-token>
# Expect: 200, image/gif, 43 bytes (1×1 transparent GIF)

curl -i "http://localhost:8000/api/v1/track/c/<valid-token>?u=aHR0cHM6Ly9leGFtcGxlLmNvbQ"
# Expect: 302 Location: https://example.com
```

## Risks

- **Gmail image proxy.** Gmail proxies images through `googleusercontent.com`, which:
  - hides the user's IP (we get Google's IP — `ip_hash` is meaningless for Gmail recipients).
  - opens once on receive (the proxy caches the image), so subsequent re-opens don't fire — open counts are floor estimates not exact.
  Document both. Not blockers.
- **Apple Mail Privacy Protection.** Similar story — pre-fetches images. Counts are upper-bound noise. Document.
- **Image-blocking clients (Outlook desktop default).** No pixel fire → no open recorded. Clicks still work. Open rate is a noisy metric; that's fine — clicks + replies are the real signal.
- **Public routes need rate limiting** to prevent token-fuzzing DoS. Use the existing rate-limit middleware (from embed widget Step 8) — 100 req/min/IP on `/track/*`. Cite in router.
- **Footer-injection compliance per jurisdiction.** Indian DPDP requires unsubscribe + sender identity; CAN-SPAM requires physical address. Both met by the auto-footer + headers. Document the address requirement: org `settings.company_address` must be non-blank for the adapter to accept a send. Validate in Step 5's adapter; fail fast with a clear error.

## Rollback

`alembic downgrade -1`. Delete files. Revert adapter + main.py + env edits. In-flight tracking links become 404s — acceptable; their TTL is short.
