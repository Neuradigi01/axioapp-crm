# Step 5 — Buttons + inputs + form fields

**Goal:** Restyle the shared button, input, select, textarea, toggle, checkbox, and radio primitives so every form in the app inherits the AIXO look automatically.
**Track:** Design Refresh — Track 3 (Shared primitives)
**Status:** COMPLETED — `.btn` / `.input` / `.textarea` / `.select` / `.field` / `.checkbox` / `.radio` / `.toggle` / `.kbd` layer landed in `aixo-components.scss`. Body font-family flipped to Inter via `--font-ui`. Material system tokens (form-field / slide-toggle / checkbox / radio) repointed to AIXO accent. Dynamic-form field renderer restyled to use the new primitives. `ng build` green.
**Depends on:** Step 1

---

## AIXO reference

### Buttons
- **Primary:** 38–40px height, `bg-accent`, `text-white`, `rounded-lg` (9px), 13–14px font-weight 600, `px-4`, optional leading icon 16px, gap-2. Hover: 4% darker (`filter: brightness(0.94)`), no elevation.
- **Secondary:** 38px, `bg-app` (surface-under-surface for contrast), `border-subtle`, `text-muted`, hover `bg-surface`. Same radius.
- **Ghost (in menus):** no border, transparent bg, hover `bg-surface`. `text-default`.
- **Danger:** text `text-red-500` (single deviation from tokens — matches AIXO's `#EF4444` for logout).
- **Icon-only:** 34×34 square, `rounded-lg`, `bg-accent-soft` for accent variant / `bg-app` for neutral.

### Inputs
- 40px height, `rounded-lg` (9px), `bg-app`, `border-subtle`, 13px, `px-3`, placeholder `text-faint`.
- Focus: `outline: 2px solid var(--accent)` (already global; no per-element rule needed).
- With leading icon: icon 18px `text-faint`, gap-2, input padding-left adjusted.

### Selects
- Same visual as inputs. Chevron icon right, 14px, `text-muted`. Native `<select>` for simple cases; Material `mat-select` restyled via `.searchable-select-panel` overrides pointed at new tokens (existing panel styles in `styles.scss` already have the plumbing — just repoint the vars).

### Textarea
- Same as input, min-height 96px, `rounded-xl` (12px), leading padding top-3.

### Toggle (switch)
- 36×20px, `rounded-full`, off = `bg-app` `border-subtle`, on = `bg-accent`. Thumb 16px, `bg-white`, transition transform 150ms.

### Checkbox / Radio
- 18×18, `rounded-md` for checkbox / `rounded-full` for radio. Off = `border-subtle` `bg-app`. On = `bg-accent` + white check icon.

### Field wrapper (`app-field`)
- Label (12.5px `text-muted` `font-weight: 500`, mb-1) → input → hint (11.5px `text-faint`, mt-1) or error (11.5px `text-red-500`, mt-1).
- Required marker: `*` in `text-accent` after label.

## Scope

1. Restyle existing components under [`APP/src/app/shared/components/`](../../APP/src/shared/components/) and [`APP/src/app/features/user/core/shared/`](../../APP/src/app/features/user/core/shared/):
   - Button component (if there's a shared one) — otherwise define reusable Tailwind class strings via `@apply` in a small `.btn` layer OR document the utility patterns.
   - Input / select / textarea directives or components.
2. **Material overrides** in [`APP/src/styles.scss`](../../APP/src/styles.scss) — repoint `.mat-mdc-form-field`, `.mat-mdc-select`, `.mat-mdc-slide-toggle`, `.mat-mdc-checkbox`, `.mat-mdc-radio-button` to the new semantic tokens. Preserves Material's a11y and keyboard behavior.
3. Dynamic form: the [`dynamic-form`](../../APP/src/app/shared/dynamic-form/) module renders custom-field forms from JSON — restyle the field wrapper + all field types.
4. Add a `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.btn-danger`, `.btn-icon` layer in `aixo-tokens.scss` (or a new `aixo-components.scss`) using `@apply` so page authors have one canonical utility.

## Files to touch

| File | Action |
|---|---|
| `APP/src/styles.scss` | modified — Material overrides repointed at new tokens |
| `APP/src/styles/aixo-components.scss` | **created** — `.btn`, `.input`, `.field-*` utility layer |
| `APP/src/app/shared/dynamic-form/*.html` | modified — new field-wrapper markup |
| `APP/src/app/shared/dynamic-form/*.scss` | modified — remove obsolete styles that fight the new look |
| `APP/src/app/features/user/core/shared/**/*.{html,scss}` | modified — restyle small shared form widgets |

**~8–10 files (within budget; split if it grows).**

## Verification

- Any form (start with contact-create) shows the new visual language without changing its logic.
- Dark and light both render legibly.
- Focus ring visible on every focusable element.
- Screen reader labels unchanged (aria-labels preserved on Material components).

## Out of scope

- Rebuilding forms — only the visual surface changes.
- Rebuilding validation error UX beyond styling.
- Rich components (date picker, color picker, file picker) — Step 7 covers dialogs/menus; deep component restyling of Material pickers deferred.
