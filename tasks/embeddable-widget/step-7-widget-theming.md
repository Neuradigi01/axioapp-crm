# Step 7 — Widget: CSS-variable theming + class-name override contract

**Goal:** Make the widget visually re-skinnable from the host site without bundle rebuilds. Ship a base stylesheet inlined in the bundle that defines every visual concern via CSS variables (`--fc-primary`, `--fc-radius`, `--fc-font`, …), all assigned to the `#furnicrm-form` container so they cascade down. Document both the variable contract and the class-name override path. Match the manager's requirement: "this can be redesigned with different classnames."
**Track:** Embeddable Widget
**Status:** Done — base stylesheet inlined into the bundle via `src/styles.ts` (template literal, no `?raw` import; the `?raw` path was tried first but vitest's CSS handler intercepts `*.css` before the `?raw` query is honoured, leaving the stylesheet empty at test time — inlining sidesteps the mismatch and keeps the bundle self-contained). 12-variable `--fc-*` contract declared on `.furnicrm-form` carries every visual concern: `--fc-primary`, `--fc-primary-contrast`, `--fc-bg`, `--fc-text`, `--fc-muted`, `--fc-border`, `--fc-border-focus`, `--fc-error`, `--fc-radius`, `--fc-spacing`, `--fc-font`, `--fc-font-size`. Low-specificity single-class selectors (no `body` ancestor, no `!important`) so host class-name overrides win without specificity tricks. `injectStyles()` is idempotent — checks for `style[data-furnicrm]` in `<head>` before appending. `index.ts` calls `injectStyles()` after mount lookup; after `renderForm`, applies the per-org `branding.accent_color` inline via `formRoot.style.setProperty("--fc-primary", …)` so the org accent kicks in even before host CSS loads (host variable overrides on an ancestor still win because they're more specific). `dev/test-host.html` stripped of placeholder field styles (widget ships its own) and seeded with commented Path A + Path B override examples. README "Theming" section ships full 12-variable contract table + 16-class catalogue + "Org-level accent (no host CSS required)" subsection. `test/styles.test.ts` adds 3 specs (injects exactly one tag, idempotent across 3 calls, `getStyles()` returns non-empty CSS exposing the variable contract). Bundle now **13.54 KB raw / 4.33 KB gzipped** (was 3.38 KB at end of Step 6; well under 30 KB ceiling). All 11 tests green in ~65 ms.
**Depends on:** Step 6 (renderer outputs the semantic classes).

---

## Scope

In-scope:

- `widget/src/styles.css` — the base stylesheet. ~80 lines. Uses CSS variables exclusively for all styling concerns. Defaults match the org's `branding.accent_color` from Step 3's config (applied dynamically at render time).
- `widget/src/styles.ts` — a function that returns the stylesheet as a string. The bundle injects it once into the document head as a `<style data-furnicrm>` tag on first init (idempotent — checks for existing tag).
- The renderer (from Step 6) uses these consistent class names:
  - `.furnicrm-form` (container)
  - `.furnicrm-form__field` (per-field wrapper)
  - `.furnicrm-form__label`
  - `.furnicrm-form__input` (covers input/select; textarea also gets it)
  - `.furnicrm-form__input--invalid`
  - `.furnicrm-form__error` (per-field error text)
  - `.furnicrm-form__button` (submit)
  - `.furnicrm-form__success` (thank-you state)
  - `.furnicrm-form__powered-by` (small footer link)
- CSS variables documented:
  - `--fc-primary` (default `#4F46E5` or the org's `accent_color`)
  - `--fc-primary-contrast` (text on primary; default `#fff`)
  - `--fc-bg` (form background; default `transparent`)
  - `--fc-text` (default `#111827`)
  - `--fc-muted` (placeholder/help text; default `#6b7280`)
  - `--fc-border` (default `#d1d5db`)
  - `--fc-border-focus` (default `var(--fc-primary)`)
  - `--fc-error` (default `#dc2626`)
  - `--fc-radius` (default `6px`)
  - `--fc-spacing` (default `12px`)
  - `--fc-font` (default `system-ui, sans-serif`)
  - `--fc-font-size` (default `15px`)
- Class-name override path: customers wanting deeper control include their own stylesheet on the host page targeting the documented `.furnicrm-form__*` classes. The base stylesheet uses **low-specificity** selectors so host overrides win without `!important`.
- Branding `accent_color` from the per-org config is applied at render time by setting `--fc-primary` inline on the `.furnicrm-form` container, overriding the stylesheet default but still themable by host CSS variables.
- README section "Theming" with examples for both paths.

Out of scope:

- No alternate "themes" (dark mode, compact mode) shipped — host CSS provides whatever look they want.
- No font preloading from the widget — `font-display: swap` and rely on system fonts as default.

## Files to touch

| File | Action |
|---|---|
| `widget/src/styles.css` | created |
| `widget/src/styles.ts` | created — exports `getStyles(): string` and `injectStyles(): void` |
| `widget/src/index.ts` | modified — call `injectStyles()` on first init; apply `accent_color` inline |
| `widget/README.md` | modified — add "Theming" section with both examples |
| `widget/dev/test-host.html` | modified — include both example overrides for visual verification |

**5 files.** Inside rule-8 budget.

## Plan

1. Write `styles.css` with all variables on `.furnicrm-form` and the rules referencing only `var(--fc-…)`:
   ```css
   .furnicrm-form {
     --fc-primary: #4F46E5;
     --fc-primary-contrast: #fff;
     --fc-bg: transparent;
     --fc-text: #111827;
     --fc-muted: #6b7280;
     --fc-border: #d1d5db;
     --fc-border-focus: var(--fc-primary);
     --fc-error: #dc2626;
     --fc-radius: 6px;
     --fc-spacing: 12px;
     --fc-font: system-ui, -apple-system, sans-serif;
     --fc-font-size: 15px;

     display: flex; flex-direction: column; gap: var(--fc-spacing);
     font-family: var(--fc-font); font-size: var(--fc-font-size); color: var(--fc-text);
     background: var(--fc-bg);
   }
   .furnicrm-form__field { display: flex; flex-direction: column; gap: 4px; }
   .furnicrm-form__label { font-weight: 500; }
   .furnicrm-form__input {
     padding: 8px 10px; border: 1px solid var(--fc-border); border-radius: var(--fc-radius);
     font: inherit; color: inherit; background: #fff; outline: none;
   }
   .furnicrm-form__input:focus { border-color: var(--fc-border-focus); }
   .furnicrm-form__input--invalid { border-color: var(--fc-error); }
   .furnicrm-form__error { color: var(--fc-error); font-size: 13px; }
   .furnicrm-form__button {
     padding: 10px 16px; border-radius: var(--fc-radius); border: 0;
     background: var(--fc-primary); color: var(--fc-primary-contrast);
     font: inherit; font-weight: 600; cursor: pointer;
   }
   .furnicrm-form__button:disabled { opacity: 0.6; cursor: not-allowed; }
   .furnicrm-form__success { padding: 12px; color: var(--fc-text); }
   .furnicrm-form__powered-by { font-size: 12px; color: var(--fc-muted); margin-top: 8px; }
   ```
2. Build `styles.ts`:
   ```ts
   import css from "./styles.css?raw";  // Vite ?raw import
   export function injectStyles(): void {
     if (document.querySelector("style[data-furnicrm]")) return;
     const tag = document.createElement("style");
     tag.setAttribute("data-furnicrm", "");
     tag.textContent = css;
     document.head.appendChild(tag);
   }
   export function getStyles(): string { return css; }
   ```
3. Modify `index.ts`: call `injectStyles()` once at first init. After fetching config, set `mount.style.setProperty("--fc-primary", config.branding.accent_color)` so the per-org accent applies even before any host CSS loads.
4. README "Theming" examples:
   ```html
   <!-- Path A: CSS variables (recommended) -->
   <style>
     #furnicrm-form {
       --fc-primary: #b45309;
       --fc-radius: 12px;
       --fc-font: "Inter", sans-serif;
     }
   </style>

   <!-- Path B: class-name overrides -->
   <style>
     .furnicrm-form__button { background: linear-gradient(...); }
     .furnicrm-form__input { box-shadow: inset 0 0 0 2px black; }
   </style>
   ```
5. Visual smoke per checklist.

## Tests

Vitest: assert `injectStyles` is idempotent (calling twice creates only one style tag).

## Smoke (browser)

```
1. Build + serve as in Step 6.
2. /dev/test-host.html shows the form with default indigo accent.
3. Edit test-host.html to add a <style> block:
   #furnicrm-form { --fc-primary: #b45309; --fc-radius: 14px; --fc-font: Georgia, serif; }
   Reload. Button is amber, inputs have larger radius, font is serif.
4. Add another <style> block overriding .furnicrm-form__button background to a gradient.
   Reload. Button now has gradient (class-name override wins, low specificity from base).
5. From the CRM Settings (Step 4), change accent_color to #16a34a. Reload test-host
   (no rebuild needed — config is fetched at runtime). Default button colour is now green,
   but the host-CSS variable override from step 3 still wins where present.
6. Right-click form → Inspect. Confirm exactly one <style data-furnicrm> tag in <head>.
   Reload. Still one (idempotent).
```

## Risks

- **CSS specificity battles:** if host CSS targets `body .some-class .furnicrm-form__input { … }` it will override our base; that's the contract. If a host customer uses `!important` on a wrong style, they have a CSS problem, not a widget problem. Document.
- **CSS variable inheritance edge cases:** Safari historically had gaps with custom properties on shadow boundaries; we don't use shadow DOM, so this is moot. Still test in Safari before declaring done.
- **Bundle size:** inlining the CSS adds ~2 KB ungzipped. Within budget.
- **Font fallback:** `system-ui` renders different on Windows vs. macOS — acceptable; host can override via `--fc-font`.

## Rollback

Revert the source files. Inject call removed = renderer styles disappear. Renderer still functions (unstyled form). Backend untouched.
