# Theming & CSS Reference — Angular App

> **When to read:** Only when your task involves CSS, SCSS, styling, theming, or colors.
> **Prerequisites:** Read `AGENT_INDEX.md` first for golden rules and project structure.

---

## 1. File Structure & Single Source of Truth

| Purpose | Path |
|---------|------|
| Token primitives (ALL values) | `src/styles/tokens.scss` |
| Dark theme mappings | `src/styles/dark.scss` |
| Light theme mappings | `src/styles/light.scss` |
| Global overrides (Material/PrimeNG) | `src/styles/styles.scss` |
| Layout common styles | `src/styles/layout-common.scss` |
| Component styles | `<component>.component.scss` — use `var()` only |

---

## 2. Three-Step Workflow (MANDATORY)

Every new color, spacing, or visual token MUST follow these 3 steps:

**Step 1: Define Tokens** (`tokens.scss`)
```scss
:root {
  --component-bg-dark: #131823;
  --component-bg-light: #f4f9ff;
}
```

**Step 2: Map in BOTH Themes**
```scss
/* dark.scss */
:root { --component-bg: var(--component-bg-dark); }
/* light.scss */
:root { --component-bg: var(--component-bg-light); }
```

**Step 3: Apply in Component**
```scss
.component { background-color: var(--component-bg); }
```

---

## 3. Token Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Primitives | `--c-{name}` | `--c-dark-bg`, `--c-white` |
| Component-specific | `--{component}-{property}-{variant}` | `--footer-nav-link-text-color` |
| State-based | `--{component}-{state}-{property}` | `--tile-hover-bg` |
| Spacing | `--spacing-{size}` | `--spacing-xs: 4px`, `--spacing-sm: 8px`, `--spacing-md: 16px`, `--spacing-lg: 24px`, `--spacing-xl: 32px` |
| Border radius | `--radius-{size}` | `--radius-sm: 5px`, `--radius-md: 10px`, `--radius-lg: 15px` |

### Variable Hierarchy

- **Base tokens:** `--c-light-bg`, `--c-dark-surface-1`, `--feedback-success`
- **Component tokens:** `--mat-card-background-color: var(--c-light-surface-1)`
- Avoid deep nesting of `var()` references (max 2 levels)

---

## 4. Component Styling Rules (STRICT)

### FORBIDDEN

- `::ng-deep` or any view encapsulation piercing — move overrides to `src/styles/styles.scss`
- Hardcoded colors (`#ffffff`, `rgba(0,0,0,0.5)`) — use `var(--token-name)`
- Inline vendor prefixes (`-webkit-`, `-moz-`) — autoprefixer handles these
- Empty rulesets
- Inline `styles:` arrays in component decorators
- `:host {}` overuse — prefer explicit class names

### REQUIRED

- `var(--variable-name)` for ALL colors/sizes
- BEM naming: `.block`, `.block__element`, `.block--modifier`
- Proper SCSS nesting with `&` for parent selectors
- Consistent transitions: `transition: background-color 0.2s ease-in-out, transform 0.2s ease-in-out`

---

## 5. Theme System Architecture

### Two-Tier Custom Properties

1. **Primitives** in `tokens.scss` — ALL values defined once on `:root`
2. **Theme files** map semantic tokens to primitives per theme:
   - `dark.scss` -> `--mat-card-background-color: var(--c-dark-surface-1)`
   - `light.scss` -> `--mat-card-background-color: var(--c-light-surface-1)`
3. **Components** consume semantic tokens: `var(--mat-card-background-color)`

### Runtime Switching

`ThemeService` (`core/services/theme.service.ts`) handles runtime theme switching via a stylesheet injection mechanism:

1. **`init()`** — Called on app startup. Reads saved theme from `localStorage` (key: `STORAGE_KEY_THEME`), falls back to system preference (`prefers-color-scheme: dark`)
2. **`toggle()`** — Switches between light and dark
3. **`applyTheme(theme)`** — The core method that:
   - Saves theme to `localStorage`
   - Enables/disables the correct `<link rel="stylesheet">` element by matching `href*="light"` or `href*="dark"` — creates the `<link>` element if it doesn't exist, then sets `link.disabled` to toggle
   - Toggles `.light-theme` / `.dark-theme` CSS class on `<body>`

The `light.css` and `dark.css` bundles are built by Angular (configured in `angular.json` with `inject: false`) and loaded/unloaded at runtime by the service. Only one theme stylesheet is active at a time.

### angular.json Styles

```json
"styles": [
  "src/styles.scss",
  { "input": "src/styles/light.scss", "bundleName": "light", "inject": false },
  { "input": "src/styles/dark.scss", "bundleName": "dark", "inject": false }
]
```

---

## 6. Global Styles (Material/PrimeNG Overrides)

Override third-party component styles in `styles.scss` or theme files, NOT in component SCSS:

```scss
.mat-card {
  background-color: var(--mat-card-background-color) !important;
  border: var(--mat-card-border) !important;
  box-shadow: var(--mat-card-box-shadow) !important;
}
```

Use `!important` sparingly — mainly for theme overrides of third-party components.

---

## 7. Design Patterns

### Hover Effects

```scss
.interactive {
  background-color: var(--element-bg);
  transition: background-color 0.2s ease-in-out, transform 0.2s ease-in-out;
  &:hover {
    background-color: var(--element-hover-bg);
    transform: translateY(-2px);
  }
}
```

### Shadows (theme-specific)

```scss
/* dark theme */
--shadow-card-blue: 0 1px 15px 1px rgba(79, 119, 251, 0.08);
/* light theme */
--shadow-card-blue: 0 2px 8px rgba(0, 0, 0, 0.1);
```

### Brand Colors

```scss
--brand-grad-1: #57bdff;
--brand-grad-2: #4f77fb;
--brand-grad-3: #6528cf;
```

---

## 8. New Color Introduction Rules

When UI tasks require colors not yet defined:

1. **Brand Consistency Analysis** — extract colors from logo files in `public/images/`, harmonize with existing brand gradients
2. **Global Color Addition Process** — add base tokens to `tokens.scss` first, map to BOTH theme files (dark + light), document context: `/* Extracted from logo blue palette */`
3. **Design Quality Requirements** — WCAG AA contrast ratios (4.5:1 minimum), hover states with 10-15% opacity variations, consistent border-radius from existing tokens

---

## 9. Quality Checklist (Before Completion)

- [ ] All colors defined in `tokens.scss`
- [ ] Both theme files updated (`dark.scss`, `light.scss`)
- [ ] No hardcoded colors in component files
- [ ] No `::ng-deep` usage
- [ ] No empty rulesets
- [ ] Proper SCSS nesting with `&`
- [ ] BEM naming for CSS classes
- [ ] Consistent transitions on interactive elements
- [ ] No compile errors
- [ ] WCAG AA contrast maintained
