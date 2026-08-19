# FurniCRM embeddable widget

Standalone JavaScript bundle that customers paste onto their own websites with a `<div>` + `<script>` snippet. Visitor submissions become leads in their FurniCRM org with `source='widget'`.

## How customer sites embed it

```html
<div id="furnicrm-form"></div>
<script
  src="https://widget.furnicrm.app/v1/widget.js"
  data-key="pk_live_AbCdef123…"
></script>
```

The script tag's `data-key` is the customer's per-org API key, issued from Settings → Embed Widget. The widget loader (Step 6) auto-runs `init()` from those data attributes — customers never write JS.

## Two modes: lead-form and AI chat (Step 15)

The same bundle renders **either** a lead-capture form OR an AI-assistant chat widget — dispatched at runtime by the embed key's `resource_type`:

| Key type | What renders | Endpoint the widget calls first |
|---|---|---|
| `resource_type='lead_form'` (default) | Lead form | `GET /api/v1/embed/config/public` |
| `resource_type='ai_assistant'` | Chat widget with `interface_config` + `styling_config` | `GET /api/v1/public/ai-assistants/assistant` |

Dispatch: `init()` tries `GET /public/ai-assistants/assistant` first with the bearer key. A 200 response means the key is scoped to an AI assistant → the chat renderer takes over. A 401 (or any other error) falls through to the existing form-renderer path. Customers embed one snippet regardless of which channel type the operator eventually issues.

### Chat mode wire

- **Session token** — persisted in `localStorage` under `crm_ai_session_<embed-key-prefix>` so a page reload keeps the conversation identifier. Namespaced per key so two assistants on the same domain don't collide.
- **CAPTCHA** — first message per session posts a Cloudflare Turnstile token. Subsequent messages within the server's 5-min TTL skip the check.
- **Streaming** — `fetch()` + `ReadableStream` (never `EventSource`) so the bearer key travels in the `Authorization` header instead of the URL query string.
- **Markdown safety** — assistant replies pass through `marked` (GFM + line breaks) then `DOMPurify.sanitize()` with `<script>` / `<iframe>` / event handlers forbidden. Links get `target="_blank" rel="noopener noreferrer nofollow"`.


## Tech decisions

| Choice | Why |
|---|---|
| Vanilla TypeScript, no framework | Bundle size: ~5–8 KB gzipped for the renderer. Angular Elements bottoms out at ~90 KB — too heavy for the customer-website critical path. |
| Single ES module at `dist/v1/widget.js` | One HTTP request, no chunk-splitting plumbing on the customer's CSP. |
| 60 KB gzipped ceiling (enforced) | Slow Indian 3G connections lose conversion past ~1s render. `scripts/check-size.ts` fails the build above the ceiling. Raised from 30 KB in Step 15 (chat mode ships `marked` + DOMPurify). |
| `/v1/` in the served path | Major-version pinning. Breaking changes ship at `/v2/widget.js` without disturbing existing customer installs. |
| Independent build pipeline (separate `package.json`) | Widget rarely changes; isolating from the Angular monorepo means frontend churn doesn't force widget rebuilds. |

## Local development

```bash
cd widget
npm install
npm run dev
# Then open http://localhost:5173/dev/test-host.html
```

Vite serves the bundle at `http://localhost:5173/v1/widget.js` with CORS open, so you can also load it from a separate static-server HTML page to verify cross-origin behaviour.

## Building

```bash
npm run build
# Outputs dist/v1/widget.js + widget.js.map
# Bundle-size guard runs at end; fails if gzipped > 30 KB.
```

## Testing

```bash
npm test
# Vitest + jsdom. Step 5 ships only smoke tests for init(); Step 6's
# renderer adds real DOM-shape + submission tests.
```

## Layout

```
widget/
├── src/
│   ├── loader.ts         # bundle entry — auto-init from <script data-key>, re-exports init()
│   ├── index.ts          # orchestrator — config → render → submit → success/error
│   ├── api.ts            # fetch wrappers + ApiError
│   ├── attribution.ts    # UTM + referrer + landing-URL capture
│   ├── renderer.ts       # builds the form DOM tree (XSS-safe: textContent only)
│   ├── styles.ts         # inline base stylesheet + injectStyles() (CSS-variable theming)
│   └── types.ts          # InitConfig / WidgetConfig / WidgetField / Attribution / SubmissionPayload
├── test/                 # Vitest specs (renderer + styles)
├── scripts/
│   └── check-size.ts     # post-build bundle-size guard (30 KB gzipped ceiling)
├── dev/
│   └── test-host.html    # local-only host page that loads the bundle
├── dist/                 # built artifacts (gitignored)
├── package.json
├── package-lock.json     # COMMIT THIS — independent from api/ and app/ lockfiles
├── tsconfig.json
└── vite.config.ts
```

## Theming

The widget ships its own base stylesheet inline — customers don't need to add any CSS to render a usable form. **Two override paths** let host sites re-skin the widget to match their brand without rebuilding the bundle:

### Path A — CSS variables (recommended)

Set any subset of the variable contract on the `#furnicrm-form` container (or any ancestor). Variables cascade down; override one, keep the rest:

```html
<style>
  #furnicrm-form {
    --fc-primary: #b45309;
    --fc-radius: 12px;
    --fc-font: "Inter", sans-serif;
  }
</style>
```

The full variable contract:

| Variable | Default | Purpose |
|---|---|---|
| `--fc-primary` | `#4F46E5` (or org's `accent_color`) | Submit button + focus accents |
| `--fc-primary-contrast` | `#fff` | Text on the primary button |
| `--fc-bg` | `transparent` | Form background |
| `--fc-text` | `#111827` | Body text + labels |
| `--fc-muted` | `#6b7280` | Placeholder + helper text |
| `--fc-border` | `#d1d5db` | Input borders |
| `--fc-border-focus` | `var(--fc-primary)` | Focused input border |
| `--fc-error` | `#dc2626` | Validation errors + invalid inputs |
| `--fc-radius` | `6px` | Border radius on inputs + button |
| `--fc-spacing` | `12px` | Gap between fields |
| `--fc-font` | `system-ui, sans-serif` | Font family |
| `--fc-font-size` | `15px` | Base font size |

### Path B — class-name overrides

For deeper control, target the documented `.furnicrm-form__*` classes directly. The base stylesheet uses **low-specificity single-class selectors**, so host CSS wins without `!important`:

```html
<style>
  .furnicrm-form__button {
    background: linear-gradient(135deg, #6366f1, #ec4899);
  }
  .furnicrm-form__input {
    box-shadow: inset 0 0 0 2px #18181b;
  }
</style>
```

Class catalogue (use these selectors; they are the public contract):

| Class | Element |
|---|---|
| `.furnicrm-form` | Outer container |
| `.furnicrm-form__form` | The `<form>` element |
| `.furnicrm-form__field` | Per-field wrapper |
| `.furnicrm-form__field--invalid` | Marker added on validation failure |
| `.furnicrm-form__label` | Field `<label>` |
| `.furnicrm-form__input` | Every `<input>` / `<select>` / `<textarea>` |
| `.furnicrm-form__textarea` | Additional class on `<textarea>` only |
| `.furnicrm-form__select` | Additional class on `<select>` only |
| `.furnicrm-form__button` | Submit `<button>` |
| `.furnicrm-form__error-banner` | Server-side error displayed above the form |
| `.furnicrm-form__powered-by` | "Powered by FurniCRM" footer |
| `.furnicrm-form--success` | Container shown after successful submit |
| `.furnicrm-form__success-icon` | Checkmark in the success state |
| `.furnicrm-form__success-message` | Thank-you message body |
| `.furnicrm-form--error` | Container shown on catastrophic load failure |
| `.furnicrm-form--loading` | Container shown while fetching config |

### Org-level accent (no host CSS required)

The org's `branding.accent_color` from Settings → Embed Widget is applied inline on the form container at render time. Owners can set a brand color without their integrator touching a single line of HTML on the host site. Host CSS variable overrides (Path A above) still win when present.

## Steps shipped here vs. coming next

- **Step 5** — package + build + placeholder `init()`.
- **Step 6** — auto-init loader from `<script>` data attributes + form renderer + submission flow + attribution capture.
- **Step 7 (this step)** — CSS-variable theming so the widget matches the host site's brand.
- **Step 8** — honeypot + min-fill-time + optional reCAPTCHA hook.
