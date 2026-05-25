# Step 5 — Widget bundle: build pipeline (Vite, vanilla TS, one ES module)

**Goal:** Establish a new top-level `widget/` package — separate from `api/` and `app/` — with its own `package.json`, Vite build config, TypeScript config, and a minimal `src/index.ts` that compiles to a single ES module `dist/v1/widget.js`. Target output < 30 KB gzipped. No framework. No Angular Elements. Decision documented here.
**Track:** Embeddable Widget
**Status:** Done — new top-level `widget/` package scaffolded (sibling to `API/`, `APP/`, `Flutter/`, `tasks/`). `package.json` pins Vite 5, TypeScript 5, Vitest 1, tsx, @types/node, jsdom — zero runtime deps (truly framework-free). `vite.config.ts` does library build → single ES module at `dist/v1/widget.js` with sourcemap, esbuild-minified, CORS open on dev + preview, jsdom test env wired. `tsconfig.json` is strict + ES2020 + DOM lib + no-unused-locals. `src/types.ts` declares `WidgetField`/`WidgetConfig`/`InitConfig`/`WidgetBranding` (mirrors backend public-config schema 1:1 so Step 6's renderer can render straight off the API response). `src/index.ts` ships a placeholder `init(config)` that validates config + renders a placeholder string. `scripts/check-size.ts` runs at end of `npm run build`, gzip-encodes the bundle, fails the build if > 30 KB (per spec — slow-3G conversion gate). `dev/test-host.html` imports the bundle exactly like a customer site would. `test/index.test.ts` covers init's three branches (valid → renders, missing mount → warns, incomplete config → warns). `widget/README.md` documents tech decisions + local-dev workflow + layout. `.gitignore` extended with explicit `widget/node_modules/` + `widget/dist/` entries (already implicitly covered by existing rules but listed for discoverability). Verified end-to-end: `npm install` clean (143 packages), `npm run build` produces `dist/v1/widget.js` + sourcemap with bundle size **0.51 KB raw / 0.32 KB gzipped** (well under the 30 KB ceiling), `npm test` runs 3 vitest specs green in 8ms.
**Depends on:** None (purely scaffolding).

---

## Scope

In-scope:

- New top-level folder `widget/` at the repo root (sibling to `api/`, `app/`, `Flutter/`, `tasks/`).
- `widget/package.json` — pinned dependencies: `vite`, `typescript`, `vitest`, `@types/node`. No runtime framework dependencies.
- `widget/tsconfig.json` — strict, target ES2020, module ESNext, no DOM lib pruning (we use the DOM heavily).
- `widget/vite.config.ts` — library build, single entry, single output `dist/v1/widget.js`, IIFE-wrapped at runtime by the loader (Step 6) so the bundle works whether dropped via `<script type="module">` or classic `<script>`.
- `widget/src/index.ts` — minimal entry; exports a single function `init(config: InitConfig)` that logs "FurniCRM widget loaded" and finds its target div. Real rendering lands in Step 6.
- `widget/README.md` — short doc: what the bundle does, how to build, how to test locally, the public install snippet contract.
- Bundle-size assertion in `vite.config.ts` build hook or as a separate `widget/scripts/check-size.ts` script — fails the build if gzipped output > 30 KB.
- `npm run build` produces `widget/dist/v1/widget.js` + `widget.js.map`.
- `npm run dev` serves the bundle at `http://localhost:5173/v1/widget.js` via Vite's preview server with CORS open, plus a tiny `widget/dev/test-host.html` page that imports the bundle exactly like a customer site would.

**Decision: framework-free vanilla TS, not Angular Elements.**

Why:
1. **Bundle size:** Angular Elements bottoms out around 90 KB gzipped; vanilla TS for a 5-field form is ~5–8 KB. The 3× difference matters on slow Indian 3G connections.
2. **CSP friendliness:** a single ES module with no eval/Function-constructor usage works with strict CSP. Angular's runtime depends on a few constructs that customers' CSPs may block.
3. **Theming surface area:** controlling CSS variables on a vanilla form is trivial. With Angular Elements, the shadow DOM boundary makes external CSS variable application possible but documentation-heavy.
4. **Build-pipeline isolation:** keeping the widget out of the Angular monorepo means its CI/build cadence is independent. The widget ships separately from the main app.
5. **No dependency drift:** the widget will rarely change. Vanilla TS minimises churn risk from framework upgrades.

Trade-off: we write rendering by hand. For a 5-field form with one submit handler, that's ~150 lines of code in Step 6. Acceptable.

Out of scope:

- No rendering logic — Step 6.
- No styling — Step 7.
- No spam protection — Step 8.
- No CI deployment pipeline for the bundle — that's an ops concern outside the build plan.

## Files to touch

| File | Action |
|---|---|
| `widget/package.json` | created |
| `widget/tsconfig.json` | created |
| `widget/vite.config.ts` | created |
| `widget/src/index.ts` | created — minimal `init()` |
| `widget/src/types.ts` | created — `InitConfig`, `WidgetField`, `WidgetConfig` shared types |
| `widget/README.md` | created |
| `widget/dev/test-host.html` | created — a basic HTML page that loads the bundle (used by Steps 6–8 smoke) |
| `widget/scripts/check-size.ts` | created — bundle-size guard |
| `.gitignore` | modified — add `widget/node_modules/`, `widget/dist/` |

**9 files.** Inside rule-8 budget; all are tiny scaffolding files.

## Plan

1. Create `widget/` folder. Initialise with `package.json` pinning Vite 5, TypeScript 5, Vitest. No runtime deps.
2. `tsconfig.json`: strict + target ES2020 + `"lib": ["ES2020", "DOM"]`.
3. `vite.config.ts`:
   ```ts
   import { defineConfig } from "vite";
   export default defineConfig({
     build: {
       lib: { entry: "src/index.ts", formats: ["es"], fileName: () => "v1/widget.js" },
       outDir: "dist",
       sourcemap: true,
       minify: "esbuild",
       rollupOptions: { output: { entryFileNames: "v1/widget.js" } },
     },
     server: { port: 5173, host: "0.0.0.0", cors: true },
     preview: { port: 5173, host: "0.0.0.0", cors: true },
   });
   ```
4. `src/types.ts` — declare the shared types so Steps 6+ have stable contracts:
   ```ts
   export interface WidgetField {
     key: string;
     label: string;
     placeholder?: string;
     required: boolean;
     order: number;
     field_type: "text" | "email" | "tel" | "textarea" | "select";
     options?: string[];
   }
   export interface WidgetConfig {
     fields: WidgetField[];
     submit_button_label: string;
     thank_you_message: string;
     thank_you_url: string | null;
     branding: { logo_url: string | null; accent_color: string; show_powered_by: boolean };
   }
   export interface InitConfig {
     key: string;
     host: string;       // backend API host
     mountId: string;    // default "furnicrm-form"
   }
   ```
5. `src/index.ts`:
   ```ts
   import type { InitConfig } from "./types";
   export function init(config: InitConfig): void {
     console.log("[FurniCRM] widget loaded", config);
     const mount = document.getElementById(config.mountId);
     if (!mount) {
       console.warn(`[FurniCRM] mount #${config.mountId} not found`);
       return;
     }
     mount.textContent = "FurniCRM widget — Step 5 placeholder";
   }
   ```
6. `dev/test-host.html`:
   ```html
   <!doctype html><html><body>
     <h1>Widget dev host</h1>
     <div id="furnicrm-form"></div>
     <script type="module">
       import { init } from "/v1/widget.js";
       init({ key: "pk_live_devplaceholder", host: "http://localhost:8000", mountId: "furnicrm-form" });
     </script>
   </body></html>
   ```
7. `scripts/check-size.ts`: gzip the built `widget.js` with `zlib.gzipSync`; fail if > 30 KB.
8. `package.json` scripts:
   - `build`: `vite build && tsx scripts/check-size.ts`
   - `dev`: `vite`
   - `preview`: `vite preview`
9. Commit `.gitignore` additions.

## Tests

Vitest is set up but no behaviour tests in this step (renderer lands Step 6). Add one trivial test asserting `init` doesn't throw when given valid config and the DOM has the mount div (jsdom environment).

## Smoke

```powershell
cd widget
npm install
npm run build
# Confirm: dist/v1/widget.js exists, sourcemap exists, size check passes.

npm run dev
# Open http://localhost:5173/dev/test-host.html (or browse to it directly)
# Console: "[FurniCRM] widget loaded {key:..., host:..., mountId:...}"
# Page: div contains "FurniCRM widget — Step 5 placeholder"
```

## Risks

- **Mono-repo lockfile drift:** `widget/` has its own `package-lock.json`, independent of `api/` (which uses `uv`) and `app/` (which uses `npm`). Document in `widget/README.md` to commit it.
- **30 KB ceiling tight for Step 7's CSS:** the bundle includes inline CSS (Step 7). If gzipped output approaches 25 KB, lean on more aggressive CSS variables and skip vendor prefixes (target modern browsers).
- **Vite preview CORS:** Vite's `preview` server respects the `cors` option. Confirm. If not, the test host page will still work (same-origin) but cross-origin testing requires running a separate static server, which is fine.
- **TypeScript strict mode + DOM lib:** confirm `getElementById` returns `HTMLElement | null` cleanly and we don't fight types unnecessarily.

## Rollback

Delete the `widget/` folder. Remove the `.gitignore` lines. Nothing else in the repo references the bundle yet.
