# Step 8 — Widget: spam protection (honeypot + token-bucket + optional reCAPTCHA hook)

**Goal:** Defend the public submission endpoint against bot abuse with three cheap, layered gates: the honeypot (already rendered by Step 6 — wire its server-side check), a minimum-fill-time check (forms submitted < 2 seconds after render are bots), and an optional Google reCAPTCHA v3 hook that orgs can enable per-key. Token-bucket rate-limit from Step 2 is the backstop.
**Track:** Embeddable Widget
**Status:** Done — three layered spam gates wired onto the submission pipeline, every reject path is silent-200 + audited. `WidgetConfigSpamProtection` (admin) + `WidgetConfigSpamProtectionPublic` (public) added to `schemas.py` with a `model_validator` that rejects `recaptcha_enabled=true` without both keys (else the gate fails closed on every legit submission). The public projection drops `recaptcha_secret_key` entirely — secret never leaves the server. `recaptcha.py` ships `verify_token(token, secret, expected_action='submit', score_threshold=0.5, remote_ip=…, http_client=…)`: POSTs to Google's siteverify via httpx, fails closed on HTTP error / non-200 / non-JSON / `success=false` / score below threshold / action mismatch. `submissions.submit()` re-ordered so key lookup runs BEFORE the spam gates — that costs one indexed DB hit per bot but enables proper per-org `min_fill_time_ms` config + audit events with org context. Pipeline now: resolve key → rate-limit → load config → honeypot → min-time → reCAPTCHA → payload validation → dedup → create contact + lead → audit. `_passes_min_fill_time` is strict: `rendered_at=None` fails when gate is enabled (bots can't bypass by omitting), future timestamps fail, > 24h ago fails, naive datetimes normalised to UTC. `_audit_rejected_spam` writes `embed.submission.rejected_spam` with `{key_id, reason: 'honeypot'|'min_time'|'recaptcha_invalid'|'recaptcha_low_score', ip_hash}` — 16-hex-char SHA-256 truncation preserves abuse pattern visibility without storing raw IPs. Router's `/embed/config/public` now projects through `WidgetConfigPublicDocument.model_validate(document.model_dump(...))` so any stray `recaptcha_secret_key` in JSONB is silently dropped on read (defence in depth). Widget side: `src/spam.ts` ships `warmRecaptcha(siteKey)` + `getToken(siteKey, action)` + `resetForTests()`; lazy-loads `https://www.google.com/recaptcha/api.js?render=…` on first form focus (module-level `scriptPromise` singleton enforces single injection), then `grecaptcha.execute(siteKey, {action: "submit"})` on submit. Failure modes all return null token → backend silent-drops. `index.ts` reads `widgetConfig.spam_protection.recaptcha_site_key`, attaches a `{once:true}` focusin pre-warm listener on the rendered `<form>`, and mints a fresh token in the onSubmit wrapper before posting. `types.ts` extended with `WidgetSpamProtection` (public projection — no secret) + `recaptcha_token?` on `SubmissionPayload`. Settings UI: `embed-api.service.ts` typed with `WidgetConfigSpamProtection` (admin shape, includes secret_key for round-trip); component adds `updateSpam(patch)` helper + 4 handlers (`onRecaptchaToggle`, `onRecaptchaSiteKeyInput`, `onRecaptchaSecretKeyInput`, `onMinFillTimeInput` with 0-60000ms clamp); HTML adds a "Spam protection" sub-panel between the powered-by toggle and the save bar (range slider for min_fill_time + reCAPTCHA toggle + conditionally-shown site/secret key inputs with a Google admin link). 24/24 backend tests green in 5.32s (6 min-fill-time, 8 recaptcha verify, 8 submit integration, 2 public projection); 16/16 widget tests green in 91ms (added 5 spam.ts specs). Widget bundle now **14.95 KB raw / 4.74 KB gzipped** (was 4.33 KB at Step 7; +0.41 KB for spam.ts + spam_protection branching, still well under 30 KB ceiling). Angular `tsc --noEmit` clean.
**Depends on:** Steps 2 (submission endpoint + rate limit), 3 (widget config — adds reCAPTCHA toggle + site key), 6 (renderer outputs honeypot + tracks `rendered_at`).

---

## Scope

In-scope:

- **Honeypot enforcement (backend):** in `submissions.submit()`, if `honeypot` field is non-empty → return 200 with `{ok: true, lead_id: null}` and log `embed.submission.rejected_spam` audit event. **Do not 4xx** — bots learn from 4xx; silent success makes them think they succeeded.
- **Min-time check (backend):** if `(server_now - rendered_at) < 2_000ms` → same silent-200 + audit. Tolerance for clock skew: if `rendered_at` is in the future or more than 24 hours in the past, treat as suspect → silent 200.
- **Per-config recaptcha settings (Step 3 extension):** add to widget config schema:
  ```json
  "spam_protection": {
    "recaptcha_enabled": false,
    "recaptcha_site_key": null,
    "recaptcha_secret_key": null,         // admin-only, never in public config
    "min_fill_time_ms": 2000              // overridable per org
  }
  ```
- **Public config endpoint** (`/embed/config/public`) returns `recaptcha_site_key` if enabled (needed by the widget to render the v3 challenge) but never `recaptcha_secret_key`.
- **Widget reCAPTCHA hook (frontend):** if `recaptcha_site_key` is present in the config, load `https://www.google.com/recaptcha/api.js?render={site_key}` lazily on first form interaction (not on page load — avoids slowing the host site). On submit, call `grecaptcha.execute(site_key, {action: "submit"})` to get a token; include as `recaptcha_token` in the submission payload.
- **Backend reCAPTCHA verification (Step 8):** if the org's config has `recaptcha_enabled=true`, the submission service POSTs the token to `https://www.google.com/recaptcha/api/siteverify` with the secret key; if score < 0.5, silent 200 + audit.
- **Settings tab additions (Step 4 extension, small):** in the Form configuration panel, add a "Spam protection" sub-panel with the toggle, site key / secret key inputs, and the min-fill-time slider.
- **Audit event:** `embed.submission.rejected_spam` carries `{key_id, reason: "honeypot" | "min_time" | "recaptcha_low_score" | "recaptcha_invalid", ip_hash}`.
- Tests: each gate independently triggers silent-200 + audit; happy path with reCAPTCHA token reaches lead creation; reCAPTCHA HTTP failure fails closed (silent 200, log).

Out of scope:

- No Cloudflare Turnstile or other CAPTCHA providers — Google reCAPTCHA v3 only for v1; hook is generic enough to swap later.
- No IP allowlist / blocklist.
- No content-based ML filtering.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/embed/submissions.py` | modified — honeypot + min-time + recaptcha checks |
| `api/src/app/core/embed/recaptcha.py` | created — `verify_token(token, secret) -> bool` (httpx call) |
| `api/src/app/core/embed/schemas.py` | modified — add `spam_protection` block to widget config schemas |
| `api/src/app/core/embed/config_service.py` | modified — split admin vs. public projections (secret_key admin-only) |
| `api/src/app/core/embed/router.py` | modified (small) — `/config/public` returns the public spam block |
| `api/src/app/core/audit/events.py` | modified (small) — already declared `embed.submission.rejected_spam`; extend payload contract |
| `api/tests/test_embed_spam.py` | created |
| `widget/src/spam.ts` | created — lazy reCAPTCHA loader + `getToken(siteKey, action)` |
| `widget/src/index.ts` | modified — call `getToken` if site key in config; include `recaptcha_token` in payload |
| `app/src/app/features/user/core/settings/integrations/embed/embed-integrations-tab.component.html` | modified (small) — spam protection sub-panel |

**10 files.** At rule-8 ceiling — sub-panel UI change is tiny.

## Plan

1. Backend: extend `WidgetConfig` schema with `spam_protection`. Admin/public projection split.
2. Implement `recaptcha.py`: `httpx.AsyncClient().post(verify_url, data={...})`; parse `{success, score, action}`; return `True` iff `success && score >= 0.5 && action == "submit"`.
3. Extend `submissions.submit()`:
   - Honeypot check: if `payload.honeypot` non-empty → silent 200 + audit.
   - Min-time check: if `(server_now - rendered_at) < min_fill_time_ms` or `rendered_at` skewed → silent 200 + audit.
   - reCAPTCHA check (if enabled): if no token → silent 200 + audit. Else verify; on failure → silent 200 + audit.
   - All gates pass → proceed to lead creation.
4. Widget: build `spam.ts`:
   ```ts
   let scriptLoaded = false;
   export async function getToken(siteKey: string, action: string): Promise<string | null> {
     if (!scriptLoaded) {
       await new Promise<void>((resolve, reject) => {
         const s = document.createElement("script");
         s.src = `https://www.google.com/recaptcha/api.js?render=${encodeURIComponent(siteKey)}`;
         s.onload = () => resolve();
         s.onerror = () => reject(new Error("recaptcha load failed"));
         document.head.appendChild(s);
       });
       scriptLoaded = true;
       await new Promise<void>(r => (window as any).grecaptcha.ready(() => r()));
     }
     try { return await (window as any).grecaptcha.execute(siteKey, { action }); }
     catch { return null; }
   }
   ```
5. Widget: in `index.ts`, if `config.spam_protection?.recaptcha_site_key`, on first user interaction (focus/input event on any form field) call `getToken(...)` to pre-warm. On submit, await a fresh token and include in payload.
6. Settings UI: add toggle + two input fields + slider; persists via existing config PUT.
7. Tests cover each rejection branch + happy path with token.

## Tests

`api/tests/test_embed_spam.py`:

- **Honeypot:** POST with `honeypot: "anything"` → 200 `{ok: true, lead_id: null}`. Audit row with `reason: "honeypot"`. No lead in DB.
- **Min time too fast:** POST with `rendered_at` set to now (server) → reject (assuming server-now also "now"). Use `freezegun` or pass `min_fill_time_ms: 500` and a `rendered_at` 100ms in the past.
- **Min time future:** `rendered_at: 2099-01-01` → reject.
- **reCAPTCHA disabled:** POST without `recaptcha_token` → success (gate not enforced).
- **reCAPTCHA enabled, no token:** config has `recaptcha_enabled: true`. POST without `recaptcha_token` → silent 200 + audit `reason: "recaptcha_invalid"`.
- **reCAPTCHA enabled, valid token:** mock `verify_token` to return True → success.
- **reCAPTCHA enabled, low score:** mock to return False → silent 200 + audit `reason: "recaptcha_low_score"`.
- **reCAPTCHA verify HTTP failure:** mock httpx to raise → fail closed (silent 200).
- **All gates pass:** valid honeypot empty + min-time met + valid token → 201 with lead created.
- **Public config does NOT include `recaptcha_secret_key`:** assert the response.

## Smoke

```powershell
# Backend tests
docker exec template_api-api-1 uv run pytest tests/test_embed_spam.py -v

# Manual: fill the form too fast (use a script):
$secret = "<pk_live_…>"
curl -X POST http://localhost:8000/api/v1/embed/leads `
  -H "X-FurniCRM-Key: $secret" `
  -H "Content-Type: application/json" `
  -d '{"full_name":"Bot","phone":"+919876543210","honeypot":"","rendered_at":"2099-01-01T00:00:00Z","attribution":{}}'
# Expect 200 with lead_id:null.

# Honeypot filled
curl -X POST http://localhost:8000/api/v1/embed/leads `
  -H "X-FurniCRM-Key: $secret" `
  -H "Content-Type: application/json" `
  -d '{"full_name":"Bot","phone":"+919876543210","honeypot":"trapped","rendered_at":"2026-05-22T10:00:00Z","attribution":{}}'
# Expect 200 with lead_id:null.

# Widget smoke: open /dev/test-host.html, configure reCAPTCHA on, reload, submit.
# Confirm grecaptcha script loads on first focus, submission includes recaptcha_token.
```

## Risks

- **Silent-200 hides legitimate user errors** — if a real user has clock skew > 24h, their submission silently disappears. Trade-off accepted; clock skew that bad is extremely rare. Document.
- **reCAPTCHA dependency on Google** — orgs in regions where Google services are intermittent will see false negatives. The toggle is per-org; they can disable.
- **`grecaptcha.execute` on every interaction:** we pre-warm on first focus and only execute on submit. Don't poll.
- **Secret key in DB:** stored plaintext in JSONB for v1. Acceptable for a per-org reCAPTCHA secret that the org pasted in themselves. Future hardening: encrypt at rest.

## Rollback

Revert the source files. Submissions stop checking honeypot/min-time/reCAPTCHA. Rate-limit from Step 2 is the last line of defence; that remains. Config rows with `spam_protection` block become ignored.
