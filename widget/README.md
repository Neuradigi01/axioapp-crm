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

## Tech decisions

| Choice | Why |
|---|---|
| Vanilla TypeScript, no framework | Bundle size: ~5–8 KB gzipped for the renderer. Angular Elements bottoms out at ~90 KB — too heavy for the customer-website critical path. |
| Single ES module at `dist/v1/widget.js` | One HTTP request, no chunk-splitting plumbing on the customer's CSP. |
| 30 KB gzipped ceiling (enforced) | Slow Indian 3G connections lose conversion past ~1s render. `scripts/check-size.ts` fails the build above the ceiling. |
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
│   ├── index.ts          # init() entry point — Step 5 placeholder, Step 6 renderer
│   └── types.ts          # InitConfig / WidgetConfig / WidgetField contracts
├── test/                 # Vitest specs
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

## Steps shipped here vs. coming next

- **Step 5 (this scaffolding)** — package + build + placeholder `init()`.
- **Step 6** — auto-init loader from `<script>` data attributes + form renderer + submission flow + attribution capture.
- **Step 7** — CSS-variable theming so the widget matches the host site's brand.
- **Step 8** — honeypot + min-fill-time + optional reCAPTCHA hook.
