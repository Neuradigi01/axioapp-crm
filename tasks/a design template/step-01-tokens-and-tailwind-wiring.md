# Step 1 — Tokens + Tailwind semantic wiring

**Goal:** Define AIXO's 12 CSS-variable tokens in dark + light + 4 vertical-accent variants, and expose them as semantic Tailwind colors so every existing and future page can restyle by swapping utility classes (never hex).
**Track:** Design Refresh — Track 1 (Foundation)
**Status:** Pending
**Depends on:** none (this is the base other steps build on)

---

## Scope

1. **Add fonts.** `@fontsource-variable/inter`, `@fontsource-variable/inter-tight`, `@fontsource-variable/jetbrains-mono` added to `APP/package.json`. Imported once in [`APP/src/styles.scss`](../../APP/src/styles.scss).
2. **New token file** `APP/src/styles/aixo-tokens.scss` with the 12 vars in `:root` (dark by default) and a `[data-theme="light"]` override block, plus the 4 `[data-accent="..."]` overrides. Values must match [`AIXO CRM.html`](AIXO%20CRM.html) exactly (captured in the track README).
3. **Extend** [`APP/tailwind.config.js`](../../APP/tailwind.config.js) with semantic colors that reference the vars via `rgb(var(--x) / <alpha-value>)` where alpha support is needed, otherwise `var(--x)` directly. Also add `fontFamily.ui/display/mono`.
4. **Legacy tokens preserved.** The existing tokens in [`APP/src/styles/tokens.scss`](../../APP/src/styles/tokens.scss), [`light.scss`](../../APP/src/styles/light.scss), [`dark.scss`](../../APP/src/styles/dark.scss) stay in place. This step *adds* the AIXO layer alongside them — Material overrides that read `--page-bg` etc. keep working. Later steps migrate pages off the legacy names one folder at a time.
5. **Remap the legacy palette values** to AIXO's values inside `light.scss` and `dark.scss` so pages that still reference the old tokens quietly pick up the new look. Names unchanged, hex values updated. Zero component changes required for existing pages to look better immediately.

## Tokens

Written verbatim into `aixo-tokens.scss`:

```scss
:root {
  --bg: #0B0C0E;
  --surface: #141619;
  --surface-2: #1C1F24;
  --border: #262A31;
  --text: #F2F4F7;
  --text-muted: #98A2B3;
  --text-faint: #667085;
  --accent: #0D9488;       /* Core CRM default (teal); overridable via data-accent */
  --accent-soft: #0D94881A;
  --font-ui: 'Inter Variable', 'Inter', system-ui, sans-serif;
  --font-display: 'Inter Tight Variable', 'Inter Tight', 'Inter', sans-serif;
  --font-mono: 'JetBrains Mono Variable', 'JetBrains Mono', ui-monospace, monospace;
}
[data-theme="light"] {
  --bg: #FAFAFA;
  --surface: #FFFFFF;
  --surface-2: #F2F4F7;
  --border: #E4E7EC;
  --text: #1D2939;
  --text-muted: #667085;
  --text-faint: #98A2B3;
}
[data-accent="real_estate"] { --accent: #4F46E5; --accent-soft: #4F46E51A; }
[data-accent="clinic"]      { --accent: #0D9488; --accent-soft: #0D94881A; }
[data-accent="salon"]       { --accent: #C026D3; --accent-soft: #C026D31A; }
[data-accent="services"]    { --accent: #2563EB; --accent-soft: #2563EB1A; }

body { background: var(--bg); color: var(--text); font-family: var(--font-ui); }
::selection { background: var(--accent-soft); }
*:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 20px; border: 3px solid transparent; background-clip: padding-box; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
```

## Tailwind semantic colors

```js
// tailwind.config.js — extended sections
theme: {
  extend: {
    colors: {
      app: 'var(--bg)',
      surface: 'var(--surface)',
      'surface-2': 'var(--surface-2)',
      subtle: 'var(--border)',           // border-subtle
      default: 'var(--text)',            // text-default
      muted: 'var(--text-muted)',
      faint: 'var(--text-faint)',
      accent: 'var(--accent)',
      'accent-soft': 'var(--accent-soft)',
    },
    borderColor: { subtle: 'var(--border)' },
    fontFamily: {
      ui: ['Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
      display: ['Inter Tight Variable', 'Inter Tight', 'Inter', 'sans-serif'],
      mono: ['JetBrains Mono Variable', 'JetBrains Mono', 'ui-monospace', 'monospace'],
    },
    boxShadow: {
      elevated: '0 12px 32px rgba(0,0,0,.35)',
      card: '0 1px 2px rgba(0,0,0,.06), 0 0 0 1px var(--border)',
    },
    borderRadius: { xl: '12px', '2xl': '14px' },
  },
},
```

**Note:** `darkMode` selector switches in **Step 2** (from `.dark-theme` class → `[data-theme="dark"]` attr). Not in this step — Step 1 is additive only.

## Legacy palette remap (values only)

In [`APP/src/styles/dark.scss`](../../APP/src/styles/dark.scss) and [`APP/src/styles/light.scss`](../../APP/src/styles/light.scss), update the hex values of the existing tokens to AIXO's palette. Names untouched:

| Legacy var | Dark value | Light value |
|---|---|---|
| `--page-bg` | `#0B0C0E` | `#FAFAFA` |
| `--surface-1` | `#141619` | `#FFFFFF` |
| `--surface-2` | `#1C1F24` | `#F2F4F7` |
| `--border-color` / `--divider-color` | `#262A31` | `#E4E7EC` |
| `--page-text` | `#F2F4F7` | `#1D2939` |
| `--page-text-secondary` / `--page-text-muted` | `#98A2B3` / `#667085` | `#667085` / `#98A2B3` |
| `--brand-grad-1`, `--brand-grad-2`, `--brand-gradient` | `#0D9488` / `#4AC7B0` / linear-gradient | same |

Full mapping in Step 1's implementation notes (agent decides granularity from the actual `tokens.scss` contents).

## Files to touch

| File | Action |
|---|---|
| `APP/package.json` | modified — add 3 `@fontsource-variable` deps |
| `APP/src/styles/aixo-tokens.scss` | **created** — AIXO tokens + global rules |
| `APP/src/styles.scss` | modified — `@use 'styles/aixo-tokens'` line + `@import '@fontsource-variable/*'` lines |
| `APP/src/styles/light.scss` | modified — remap hex values only |
| `APP/src/styles/dark.scss` | modified — remap hex values only |
| `APP/tailwind.config.js` | modified — add semantic colors, fontFamily, boxShadow, borderRadius extensions |

**6 files.**

## Verification

- Load the app in either theme — `body { background: var(--bg) }` is the new dark/light bg (immediately visible even before any component migrates).
- Devtools → `<html>` element has `data-theme` attribute set (from Step 2; for Step 1 alone, no attribute means the `:root` dark defaults apply).
- Tailwind classes `bg-surface`, `text-muted`, `border-subtle` render correctly in a scratch `<div>`.
- `font-ui`, `font-display`, `font-mono` all resolve to their variable fonts (Devtools → Rendered Fonts tab shows Inter / Inter Tight / JetBrains Mono).
- `@media (prefers-reduced-motion)` — set OS-level reduce motion → any existing CSS transition becomes instant.

## Out of scope

- Migrating any existing component's classes off `bg-white` / `bg-zinc-900` — Step 5+ handles primitives; Steps 8+ handle pages.
- The theme service change (Step 2).
- Removing any legacy token — they stay for gradual migration.
