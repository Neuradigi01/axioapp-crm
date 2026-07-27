# Step 2 — ThemeService migration + toggle UI

**Goal:** Switch the theme mechanism from "swap stylesheet + toggle `.dark-theme` on `<body>`" to "set `data-theme` attribute on `<html>`". Add a visible toggle in the header (three states: light / dark / system). Kill FOUC with an inline pre-boot script.
**Track:** Design Refresh — Track 1 (Foundation)
**Status:** Pending
**Depends on:** Step 1

---

## Scope

1. **Migrate [`APP/src/app/core/services/theme.service.ts`](../../APP/src/app/core/services/theme.service.ts)** so `applyTheme(theme)`:
   - Sets `document.documentElement.setAttribute('data-theme', theme)` (was: body class swap).
   - Continues to disable/enable the `light.css` / `dark.css` bundle links exactly as before (Material still needs the separate compiled palettes; the `data-theme` attr controls the AIXO token layer).
   - Removes the legacy `document.body.classList.add('${theme}-theme')` line, or keeps it as a temporary shim (agent's call — remove if no SCSS selector still reads `.dark-theme` / `.light-theme`; keep otherwise, remove in a follow-up step).
2. **Flip Tailwind darkMode** in [`APP/tailwind.config.js`](../../APP/tailwind.config.js) from `['class', '.dark-theme']` → `['selector', '[data-theme="dark"]']`. Every existing `dark:` utility class keeps working.
3. **Inline pre-hydration script** in [`APP/src/index.html`](../../APP/src/index.html):
   ```html
   <script>
     (function() {
       try {
         var c = localStorage.getItem('theme-choice');
         var t = c === 'dark' || c === 'light' ? c
               : (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
         document.documentElement.setAttribute('data-theme', t);
         var a = localStorage.getItem('theme-accent');
         if (a) document.documentElement.setAttribute('data-accent', a);
       } catch(e) {}
     })();
   </script>
   ```
   Placed **inside `<head>`, before any stylesheet link.** This sets the attribute before Angular parses, so the very first paint is already in the correct theme.
4. **Header toggle** — a small three-state toggle in the header (sun / moon / monitor icons, radio group). Wires to `ThemeService.set(choice)`. Persists to `localStorage.setItem('theme-choice', choice)`. Placement: leftmost item in the header's right-aligned action cluster, before the notif bell.
5. **Settings → Appearance** — a matching card in [`APP/src/app/features/user/core/settings/`](../../APP/src/app/features/user/core/settings/) with the same three-state control + a preview swatch grid.
6. **Storage key name** — align on `theme-choice` (used by the pre-hydration script). The current key from [`STORAGE_KEY_THEME`](../../APP/src/app/core/constants/app.constants.ts) constant may need a rename or the pre-hydration script needs to read the existing key. Agent picks whichever avoids a one-time reset for logged-in users; migrate the value on first load if the constant name changes.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/core/services/theme.service.ts` | modified — swap `body.classList` for `documentElement.setAttribute('data-theme', ...)` |
| `APP/tailwind.config.js` | modified — `darkMode: ['selector', '[data-theme="dark"]']` |
| `APP/src/index.html` | modified — inject the pre-hydration `<script>` in `<head>` |
| `APP/src/app/features/user/core/layout/header.component.html` | modified — add theme toggle button-group in the right action cluster |
| `APP/src/app/features/user/core/layout/header.component.ts` | modified — inject `ThemeService`, wire the toggle |
| `APP/src/app/features/user/core/settings/appearance/appearance.component.{ts,html}` | created OR modified if Settings→Appearance already exists — three-state toggle + preview |
| `APP/src/app/core/constants/app.constants.ts` | modified (optional) — align storage key with `'theme-choice'` |

**6–7 files.**

## Verification

- Hard refresh in dark → **no flash** of light theme (previously visible for ~200ms).
- Header toggle: click sun → instantly light. Click moon → instantly dark. Click monitor → follows OS.
- OS toggle in system mode → app flips live via `matchMedia('change')` listener.
- `localStorage.getItem('theme-choice')` reflects the chosen mode.
- `<html data-theme="dark">` or `="light"` set at all times.
- Every existing `dark:bg-*` / `dark:text-*` utility class still activates in dark mode.
- Legacy `<link>` `.light.css` / `.dark.css` still switch (verify by Devtools → Network → check disabled state).

## Out of scope

- Removing Material Design or the two compiled palettes — future track.
- Redesigning the toggle beyond a three-icon segmented control — Step 7 (menus) polishes it.
- Adding the vertical-accent picker UI to Settings → Appearance — separate future step.
