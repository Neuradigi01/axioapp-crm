# Step 8 — Backend: open pixel + link rewriting + delivery state

**Goal:** Per-send tracking: a 1×1 tracking pixel injected into outbound HTML records opens. Outbound links are rewritten through a redirector to record clicks. Both update per-message + per-template + per-sequence stats. Compliance: `List-Unsubscribe` headers + unsubscribe link footer.
**Track:** App Updates → Email
**Status:** COMPLETED — Migration `0086_add_email_tracking` lands `email_message_opens` + `email_message_clicks` (both with `apply_rls` + the message-grouped `(message_id, opened_at)` / `(message_id, clicked_at)` indexes), plus `contacts.email_opt_out` BOOL DEFAULT FALSE + `contacts.email_opt_out_at` TIMESTAMPTZ (added via `ALTER TABLE … ADD COLUMN IF NOT EXISTS` so re-running on a partial-migration env is safe). `core/email/tracking/` sub-package ships seven files: `tokens.py` (HMAC-SHA256 truncated to 16-byte sig, urlsafe-base64 payload of `uuid_bytes + b':' + kind_char`, format `<payload_b64>.<sig_b64>`; `decode()` returns None on ANY failure — tampered sig, malformed structure, unknown kind, bad UUID — so the router treats every failure as a constant 404 with no DB hit; `_get_key()` reads `TRACKING_HMAC_KEY` env var and raises `_MissingKey` on first use so misconfiguration is loud), `models.py` (two narrow ORM rows + `TenantScoped` mixin), `pixel.py` (pure: case-insensitive `</body>` regex; inserts the `<img src="…/o/{token}" width="1" height="1" style="display:block;border:0;height:1px;width:1px;">` immediately before body close; appends at end when no body tag; wraps empty input in `<div>` so the HTML alternative isn't degenerate), `link_rewriter.py` (regex-based `<a href>` walker that handles single + double quoted attributes; skips `mailto:`, `tel:`, `sms:`, `data:`, `javascript:`, in-doc `#` anchors, and our own tracker URLs for idempotency; preserves other tag attributes; rewrites to `…/c/{token}?u={base64url(original_href)}`), `footer.py` (pure builder: composes single-line address from `OrgSettings.address_line1/2, city, state, postal_code, country`; HTML-escapes `org_name`; `has_required_address()` gate the adapter uses to fail-fast on missing address; `append()` mirrors pixel's body-close insertion logic), `router.py` (three public unauthenticated endpoints — `GET /track/o/{token}` returns 43-byte transparent GIF + records open; `GET /track/c/{token}?u=<b64>` decodes the target URL, validates http/https, 302 redirects, records click; `GET /track/unsubscribe/{token}` sets `email_opt_out=true/now`, cancels any `active` or `paused_on_reply` sequence enrollments for the contact + skip-flags their pending step rows with reason `contact_unsubscribed`, renders confirmation HTML; module-level `InMemoryRateLimiter(100/60s/IP)` on every request prevents token-fuzzing DoS; IP + UA hashed to 16-char sha256 prefix — never raw PII; all recording is best-effort wrapped in try/except so DB hiccups don't break the pixel/redirect; per-row tenant context set via raw-SQL `messages.id → org_id` lookup before any RLS-scoped INSERT). `core/contacts/models.py` extended with `email_opt_out: Mapped[bool]` + `email_opt_out_at: Mapped[datetime | None]` columns. `core/conversations/adapters/email.py` extended: two new `HTTPException` subclasses — `OptedOut(451)` (RFC-aligned "Unavailable For Legal Reasons" for the compliance refusal) and `MissingCompanyAddress(400)`; `send_email` pipeline gains four steps before MIME assembly: (1) opt-out check raises `OptedOut`; (2) `OrgSettings` lookup + `has_required_address()` gate raises `MissingCompanyAddress`; (3) pre-allocate `messages.id = uuid.uuid4()` so the tracking tokens encode the actual row id (solves the chicken-and-egg between token + Message-row); (4) thread `body_html` through `pixel.inject → link_rewriter.rewrite → footer.append`. `_build_outbound_mime` gains `list_unsubscribe_url` + `list_unsubscribe_mailto` kwargs that set `List-Unsubscribe: <mailto:…>, <{base}/unsubscribe/{token}>` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` per RFC 8058 (Gmail / Outlook / Apple Mail show a one-click unsubscribe button when both headers present). Three new env vars added to `.env.example`: `TRACKING_BASE_URL` (default `http://localhost:8000`; no trailing slash), `TRACKING_HMAC_KEY` (32-byte secret; rotation invalidates every in-flight tracking link), `LIST_UNSUBSCRIBE_MAILTO` (default `unsubscribe@furnicrm.app`). Tracking router included in `main.py` under `/api/v1` — unauthenticated by design. Tests cover: token roundtrip across all three kinds (`o` / `c` / `u`); tampered-signature rejected; tampered-payload rejected; malformed token rejected (empty, no dot, just dot, missing-half); unknown kind rejected at encode; pixel injection (before `</body>`, case-insensitive, appended when no body, wrapped on empty, correct URL format, trailing-slash normalisation); link rewriter (http + https rewritten; mailto + tel + anchor + data + javascript skipped; idempotent on already-tracker URLs; preserves class + target attributes; multiple links all rewritten; single-quoted href works); footer (has_required_address true/false/none; build includes name + address + unsubscribe; HTML escaping protects against `<script>` injection in `org_name`; append before body close; append no body tag). **Notable adaptations from the spec:** (a) **Stdlib regex instead of BS4** — matches Step 6's no-new-deps pattern; (b) **Footer is a separate `footer.py`** rather than folded into the adapter — same composition pattern as `pixel` / `link_rewriter`, lets the adapter's pipeline read as `pixel → links → footer`; (c) **`OptedOut` is HTTP 451** ("Unavailable For Legal Reasons") — explicit RFC alignment with the compliance refusal; (d) **Adapter file path is `core/conversations/adapters/email.py`** not `…/channels/email_adapter.py` — same path adaptation as Step 5; (e) **Pre-allocated `messages.id`** instead of two-phase write-token-then-update — solves the chicken-and-egg cleanly; (f) **CAN-SPAM address validation lives in the adapter** (not Step 5) — Step 5 didn't have the footer/headers context to validate against; (g) **`/track/c/` decode validates `http:` / `https:` prefix** before redirecting — defence-in-depth against forged tokens redirecting to `javascript:` URLs; (h) **Best-effort recording** — every DB INSERT in the router is wrapped in try/except so the pixel always renders and the click always redirects, even when the DB is unhealthy. Smoke verified: imports succeed for all new modules; routes mount at `/api/v1/track/o/{token}`, `/api/v1/track/c/{token}`, `/api/v1/track/unsubscribe/{token}`; migration applies cleanly (DB at `0086_add_email_tracking`); pytest tests/test_email_tracking.py → **30 passed in 6.35s**; tests/test_email_sequences.py → **18 passed** (no regression). Pending manual: paste `TRACKING_HMAC_KEY=...` (generate via `python -c "import secrets; print(secrets.token_urlsafe(32))"`) into your `.env` and restart the api container so `send_email` can encode tokens at runtime.
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
