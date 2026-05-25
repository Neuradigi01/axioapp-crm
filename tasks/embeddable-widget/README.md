# Embeddable Lead-Capture Widget

A standalone JavaScript bundle that customers (Indian furniture retailers using FurnitureCRM) can drop onto their own websites with a `<div id="…">` + `<script>` snippet. Submissions land as leads in their CRM org with `source='widget'`. The widget is re-skinnable via CSS variables so it matches the host site's design, has built-in spam protection, captures UTM/referrer attribution, and authenticates each submission with a per-org public API key.

## Why this exists

Most furniture retailers have a marketing website (often a basic Shopify, WordPress, or static HTML site). When a visitor wants a quote, they fill in a "Contact us" form — which today either emails the retailer (and gets lost) or feeds a separate inbox the sales team forgets to check. The CRM should own that capture surface directly: every web-form submission becomes a lead, gets routed to the right rep, and is visible in the kanban next to walk-ins, calls, and ads.

Per the manager spec (2026-05-22): expose an API; customer drops `<div id="…">` + `<script>` on their site; widget renders our form into the div; submissions feed the CRM; the widget is restylable to match the host site.

| Gap | What's missing today |
|---|---|
| **No public lead-submission API** | Every existing lead endpoint requires admin JWT. There is no path for a website visitor (unauthenticated) to submit a lead. |
| **No public auth model** | No per-org API keys with limited scope. Tokens today are user-bound. |
| **No JS distribution** | The Angular app is too heavy to embed (~1 MB). A widget bundle must be its own build, < 30 KB gzipped, framework-free. |
| **No spam protection** | A public endpoint without rate-limit/honeypot/captcha would fill the CRM with garbage in days. |
| **No attribution capture** | UTM tags, referrer, landing-page URL — all the things marketing actually wants — are not captured anywhere. |
| **No theming contract** | There is no way for a customer to make a CRM-served form match their site's brand. Hardcoded styles would clash with every host site. |
| **No embed-status visibility** | Owner has no way to see "is the widget being loaded on the customer's site? Are submissions arriving? Is the key being abused?" |

## What this does NOT do

- **Does not render multi-step forms.** Single-page form only for v1. Multi-step (`Step 1: Contact → Step 2: Project details`) deferred.
- **Does not render the org's full custom-fields tree.** The widget exposes a configurable subset (default: name, phone, email, interest, notes). Each org chooses which fields appear in their widget; "expose every custom field" is not the default — too easy to leak.
- **Does not handle file uploads.** A v1 lead form is text-only. File upload (e.g. "upload a photo of your living room") is a separate, larger surface.
- **Does not embed deep CRM functionality** — no chat, no calendar booking. Lead capture only.
- **Does not auto-redirect.** Customer configures a thank-you redirect URL in Settings; widget honours it. No default redirect.
- **Does not touch `features/admin/`.**
- **Does not introduce a new framework.** Vanilla TypeScript compiled to a single ES module + a thin loader script. No React, no Vue, no Angular Elements. (Decision documented in Step 5.)

## Acceptance criteria

A new Owner, on a fresh org, can:

1. Navigate to `/user/settings/integrations/embed` → see "Generate embed key" button. Click it. A modal shows a one-time-display secret key (`pk_live_…`) + a copy-paste snippet:
   ```html
   <div id="furnicrm-form"></div>
   <script src="https://widget.furnicrm.app/v1/widget.js" data-key="pk_live_…"></script>
   ```
2. Paste the snippet into a static HTML test page. Open in browser. Form renders inside the div with default styling: name, phone, email, interest, notes, Submit button.
3. Fill in the form and submit. The form shows a success state. In the CRM, a new lead appears with the entered values, source badge "Widget", and the page's URL captured as the referrer.
4. Set CSS variables on the host page:
   ```html
   <style>
     #furnicrm-form { --fc-primary: #b45309; --fc-radius: 12px; --fc-font: "Inter", sans-serif; }
   </style>
   ```
   Reload. Form's primary button is now amber, inputs have rounded corners, and the font matches.
5. Optional: override class names by including a custom stylesheet that targets `.furnicrm-form__field`, `.furnicrm-form__input`, `.furnicrm-form__button`. Both theming paths work; CSS variables are recommended.
6. Submit the form 11 times in 60 seconds from the same IP → 11th submission returns a 429 error, in-form error message displays.
7. As Owner, navigate to `/user/settings/integrations/embed/log` → see every submission attempt for the last 30 days with timestamp, source URL, IP (last octet hashed), and outcome (success / spam-blocked / 429).
8. Revoke the key. Future submissions return 401; the form shows "this form is no longer active".

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend: `embed_keys` table + key issuance/revocation](step-1-backend-embed-keys.md) | Pending | ~½ day |
| 2 | [Backend: public `POST /api/v1/embed/leads` endpoint + rate limit](step-2-backend-public-submission-endpoint.md) | Pending | ~1 day |
| 3 | [Backend: per-org widget config (visible fields, thank-you URL, branding)](step-3-backend-widget-config.md) | Pending | ~½ day |
| 4 | [Frontend (Settings): Embed Integrations tab — keys + config + snippet](step-4-frontend-settings-embed-tab.md) | Pending | ~1 day |
| 5 | [Widget bundle: build pipeline (Vite, vanilla TS, one ES module)](step-5-widget-build-pipeline.md) | Pending | ~½ day |
| 6 | [Widget: loader script + form renderer](step-6-widget-loader-and-renderer.md) | Pending | ~1 day |
| 7 | [Widget: CSS-variable theming + class-name override contract](step-7-widget-theming.md) | Done | ~½ day |
| 8 | [Widget: spam protection (honeypot + token-bucket + reCAPTCHA hook)](step-8-widget-spam-protection.md) | Done | ~½ day |
| 9 | [Frontend (Settings): submission log + abuse signals](step-9-frontend-submission-log.md) | Done | ~½ day |
| 10 | [Widget: opt-in custom fields on the form](step-10-custom-fields-on-widget.md) | Done | ~½ day |

**Total: ~6 working days.** Each step verifiable in under 30 min per Rule 8; stop-and-report per Rule 9.

## Dependencies

- Manual Lead Entry Step 1 (`lead.source` enum includes `widget`) — required.
- Phase 1.5 (permissions, audit, org settings) — required.
- Phase 1.7 (audit log) — every key issued/revoked + every submission emits an audit event.
- Phase 2.11 (Leads backend) — widget submissions create leads via the same service.
- Phase 2.4 (Contacts backend) — for the contact created alongside each lead.
- Phase 4.1 (pack manifest) — the furniture pack may later contribute a default widget config (e.g. include an "Interest in: Sofas | Beds | Dining | Wardrobes" select); not blocking for this track.

## File budget

| Area | Files |
|---|---|
| Backend Step 1 | 1 migration + 4 new (`core/embed/{models,schemas,service,router}.py`) + 1 modified (`permissions/registry.py`) + 1 test |
| Backend Step 2 | 1 new (`core/embed/submissions.py` — public submission service) + 1 new (`core/embed/rate_limit.py`) + 1 modified router + 1 test |
| Backend Step 3 | 1 migration + 2 modified (model + router) + 1 test |
| Frontend Step 4 | 4 new (settings tab `.ts/.html` + key-modal `.ts/.html`) + 1 new `embed-api.service.ts` + 1 modified settings routes |
| Widget Step 5 | 1 new `widget/` top-level folder + `package.json`, `tsconfig.json`, `vite.config.ts`, `src/index.ts` stub |
| Widget Step 6 | 1 new `src/loader.ts` + 1 new `src/renderer.ts` + 1 new `src/api.ts` + 1 new `dist/` build artifact |
| Widget Step 7 | 2 new (`src/styles.css` + theming docs in widget README) |
| Widget Step 8 | 1 new `src/spam.ts` + 1 modified `submissions.py` backend (token bucket per key + per IP) |
| Frontend Step 9 | 2 new (`submission-log.component.ts/.html`) + 1 modified `embed-api.service.ts` + 1 modified backend router (list submissions endpoint) |

**Total ~30 files across 9 steps.** Largest single step (Step 6) ships ~5 files inside the widget bundle, comfortably under rule-8. The widget folder is a new top-level package; it does NOT live under `app/` (separate build, separate deploy, separate concerns).

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Widget submissions create leads with `source='widget'` and `actor_user_id=NULL` | Step 2's submission service; cannot be overridden by widget payload. |
| Per-org API keys never leave the issuance modal | Stored hashed (Argon2id) server-side. Owner cannot retrieve the key after closing the modal — must rotate to get a new one. |
| Rate limiting per key + per IP | Token bucket (100 req / hour / key default, 10 req / hour / IP default). Configurable per org in Step 3. |
| Honeypot + minimum-fill-time spam gates | Step 8 — invisible field; if filled, silently 200 with no lead created (don't tell the bot). |
| UTM + referrer + landing URL captured | Step 6 — widget reads `document.referrer`, `window.location`, and `URLSearchParams` and POSTs them with every submission. |
| CORS open to any origin | Step 2 — `Access-Control-Allow-Origin: *` on the public endpoint; key auth is the gate, not origin. |
| Widget bundle is framework-free and < 30 KB gzipped | Step 5's build config enforces; bundle-size check in CI. |
| Audit events emitted on key actions | `embed.key.issued`, `embed.key.revoked`, `embed.submission.accepted`, `embed.submission.rejected_spam`, `embed.submission.rate_limited`. |
| `org_id` on every new table | Yes. |
| `core/` never imports `packs/` | This is core-only. The furniture pack may later contribute default field choices (e.g. interest categories), but the widget code itself stays in core. |

## Self-check against the 10 rules

- Rule 1: Pure core. Widget bundle is its own top-level package; not under `packs/`.
- Rule 2: `embed_keys`, `widget_configs`, `embed_submissions` all carry `org_id` + RLS.
- Rule 3: Custom fields layer unaffected. Widget config exposes a subset of standard + custom fields to render.
- Rule 4: Widget renders dynamically from `GET /embed/config?key=…`; never hardcodes the form structure.
- Rule 5: Sidebar/menu unchanged in core (the widget runs externally). Settings tab plugs into the existing settings tab registry.
- Rule 6: One new permission key `settings.integrations.embed.manage`.
- Rule 7: `pack.yaml` unaffected. Pack may contribute default widget-field suggestions later.
- Rule 8: 30 files across 9 steps, each step ≤ 6 files (Step 4 is largest at 6).
- Rule 9: Stop-and-report after each step.
- Rule 10: No TODOs. CSP/CORS configured from day one. The rate-limiter is the real thing, not a placeholder.

## Operational concerns

- **Widget hosting:** the built `widget.js` needs to be served from a stable URL like `https://widget.furnicrm.app/v1/widget.js`. Deployment of the bundle to that origin is its own concern (likely an S3+CloudFront or Cloudflare Pages setup — orthogonal to this build). For local dev, the bundle is served by `vite preview` at `http://localhost:5173/v1/widget.js`; the snippet in Settings shows `data-host` so the loader knows where the API lives.
- **Versioning:** the URL contains `/v1/` so breaking changes can ship `/v2/` without breaking existing customer installs.
- **No build-time secrets in the widget.** The bundle is public; nothing sensitive baked in.

## After this track

- Every furniture retailer's website can become a lead funnel for their CRM in 60 seconds.
- The submission log gives marketing real attribution data for the first time.
- The widget pattern carries over to a future "embed booking widget" surface (calendar) and "embed catalog browser" surface — both clearly out of scope for this track but architecturally enabled.
