# Design Refresh — AIXO CRM visual system

Adopt the visual language of the reference design at [`AIXO CRM.html`](AIXO%20CRM.html) across every page of the Core CRM Angular app, without touching any business logic. Tailwind stays the styling framework (per CLAUDE.md rule 4 / stack lock). Both **dark and light** modes are mandatory, driven by a `data-theme` attribute on `<html>`.

## Why

- Current CRM inherits from a Material-heavy legacy template; look-and-feel is inconsistent across modules and reads as "unfinished admin panel."
- AIXO's design system is production-tier (Superhuman / Linear / Notion tier): 12 semantic tokens, dark-first with a light theme flip, monochrome surfaces + one accent, generous rounding, three font families, subtle motion. Every screen in AIXO maps 1:1 to a module we already ship.
- We already have a `ThemeService` + Tailwind + two token stylesheets — the refresh reuses that plumbing rather than re-inventing it.

## Scope

**In** — CSS / markup / component templates for:
- Every route under `/user/**` ([features/user/core/*](../../APP/src/app/features/user/core/) and [features/user/packs/*](../../APP/src/app/features/user/packs/))
- Every route under `/accounts/**` ([features/accounts/*](../../APP/src/app/features/accounts/)) — realign to new tokens
- **`features/admin/`** — visual/CSS only (this is a deliberate override of CLAUDE.md's "admin is untouched" rule for this track only; recorded in `project_design_refresh_track.md` memory)
- Global styles: [`APP/src/styles.scss`](../../APP/src/styles.scss), [`APP/src/styles/tokens.scss`](../../APP/src/styles/tokens.scss), [`APP/src/styles/light.scss`](../../APP/src/styles/light.scss), [`APP/src/styles/dark.scss`](../../APP/src/styles/dark.scss)
- Tailwind config: [`APP/tailwind.config.js`](../../APP/tailwind.config.js)
- Theme service: [`APP/src/app/core/services/theme.service.ts`](../../APP/src/app/core/services/theme.service.ts)

**Out** — backend, routes, guards, services, RBAC, form validation, HTTP wiring, business logic. No file under `api/`, no `*.service.ts` that isn't `ThemeService`, no route reshuffles.

## Design system captured from AIXO

### CSS-variable tokens (exact values)

Dark (default):
```
--bg:         #0B0C0E
--surface:    #141619
--surface-2:  #1C1F24
--border:     #262A31
--text:       #F2F4F7
--text-muted: #98A2B3
--text-faint: #667085
--accent:     #4F46E5   /* default; overridable per vertical */
--accent-soft:#4F46E51A /* accent @ 10% alpha */
--font-ui:      'Inter', system-ui, sans-serif
--font-display: 'Inter Tight', 'Inter', sans-serif
--font-mono:    'JetBrains Mono', ui-monospace, monospace
```

Light (`[data-theme="light"]` on `<html>`):
```
--bg:         #FAFAFA
--surface:    #FFFFFF
--surface-2:  #F2F4F7
--border:     #E4E7EC
--text:       #1D2939
--text-muted: #667085
--text-faint: #98A2B3
/* accent + fonts inherit the default block */
```

Vertical accent overrides (`[data-accent="X"]`):
```
real_estate → #4F46E5 (indigo)
clinic      → #0D9488 (teal)
salon       → #C026D3 (fuchsia)
services    → #2563EB (blue)
```

For Core CRM (industry-neutral), the default accent is **`#0D9488` teal** (matches AIXO's thumbnail and reads as a "product" color, not a "brand" color); the four `data-accent` presets stay wired so an Owner can switch later from Settings → Appearance.

### Global rules
- `body { background: var(--bg) }`
- `::selection { background: var(--accent-soft) }`
- `*:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px }`
- Scrollbar: 10px, thumb = `var(--border)` with 3px transparent border + `border-radius: 20px`, thin monochrome
- `@media (prefers-reduced-motion) { *{animation:none!important;transition:none!important} }`

### Shape language
- Cards: `rounded-xl` (12px) / `rounded-2xl` (14–16px), `1px` solid `var(--border)`, `bg-surface`.
- Buttons: pill for primary CTAs (`rounded-full` or `rounded-lg` 9–10px), icon-only 34px square, radius 9px.
- Inputs: 40px height, `rounded-lg`, `bg-bg` (surface-under-surface for depth), 13px text, 1px `border-subtle`.
- Menus / popovers: `rounded-xl` 12px, `bg-surface-2`, `shadow-elevated` (0 12px 32px rgba(0,0,0,.35) in dark, softer in light).
- Section headings: `font-display`, `font-weight: 600`, `letter-spacing: -.02em`, 14–26px.
- Micro-labels (all-caps section titles): 11px, `text-faint`, `letter-spacing: .06em`, `text-transform: uppercase`.
- Numeric values / IDs / timestamps: `font-mono`.

### Layout blueprints (from AIXO screens)

- **App shell:** collapsible left rail (expanded: 264px, collapsed: 68px), workspace switcher card at top, section-grouped nav in middle, profile at bottom. Thin 52px header with search / cmd-K / notif bell / avatar. Optional trial banner strip (36px) above main.
- **Dashboard:** greeting header + date-range pill · signature strip (gradient-lit pipeline overview) · KPI grid (auto-fit minmax 210px) · 2-col split (revenue chart + pipeline funnel) · ops KPIs · 2-col split (today's follow-ups + appointments) · recent activity card.
- **List pages (Contacts / Leads / etc):** page-header (title + count + primary action) · filter chip row · search input · table (borderless rows separated by 1px border, hover = surface-2, checkbox column, row action on hover).
- **Detail modals / drawers:** side sheet from right, 480–560px wide, `bg-surface-2`, header with close, sections separated by border, sticky footer with primary/secondary actions.
- **Pipeline board (Leads):** horizontal Kanban, column headers with count chips, cards `rounded-xl` with contact avatar + title + tag chips + last-activity mono timestamp.
- **Conversations:** three-pane (channel/inbox nav 240px · thread list 320px · thread pane flex-1), channel-branded bubbles inside the pane (WhatsApp green, Messenger blue, Instagram gradient, Telegram cyan) but the CHROME around them stays neutral.
- **Settings / module page:** two-column (left sub-nav 220px, right content), content is card-grouped sections with borders and micro-labels.
- **Empty states:** centered icon (34px stroke, `text-faint`) → bold single line → primary CTA button pill.

## Acceptance

- Every page under `/user/**`, `/accounts/**`, `/admin/**` renders with the AIXO look and passes both dark and light mode without regressions.
- No visible Material Design leakage (no default `mat-*` colors, no Material dropdown shadows, no Roboto).
- Toggle in header AND in Settings → Appearance flips instantly, persists to `localStorage`, respects `prefers-color-scheme` when set to `'system'`, no FOUC on refresh.
- Every semantic surface uses tokens (no page carries hardcoded `#hex` colors except for third-party channel branding inside Conversations bubbles).
- `data-accent` on `<html>` switches accent live across every screen with zero page work.

## Steps

Grouped into 5 tracks. Each step is independently reviewable; pause/report after each per rule 9.

### Track 1 — Foundation

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Tokens + Tailwind semantic wiring](step-01-tokens-and-tailwind-wiring.md) | COMPLETED | ~½ day |
| 2 | [ThemeService migration + toggle UI](step-02-theme-service-and-toggle.md) | COMPLETED | ~½ day |

### Track 2 — App shell

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 3 | [Sidebar rail + workspace switcher](step-03-sidebar-rail-and-workspace-switcher.md) | COMPLETED | ~1 day |
| 4 | [Header + trial banner + command palette shell](step-04-header-banner-cmdk.md) | COMPLETED | ~½ day |

### Track 3 — Shared primitives (`core/shared/`)

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 5 | [Buttons + inputs + form fields](step-05-buttons-inputs-forms.md) | COMPLETED | ~1 day |
| 6 | [Cards + tables + chips + badges + empty states](step-06-cards-tables-chips.md) | COMPLETED | ~1 day |
| 7 | [Dialogs + menus + toasts + notifications dropdown + avatar menu](step-07-dialogs-menus-toasts.md) | COMPLETED | ~1 day |

### Track 4 — Page pass (one focus per step)

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 8 | [Dashboard (signature strip + KPIs + funnel + follow-ups)](step-08-dashboard.md) | COMPLETED | ~1 day |
| 9 | [Contacts (list + detail drawer + import)](step-09-contacts.md) | COMPLETED | ~1 day |
| 10 | [Leads (list + pipeline board)](step-10-leads.md) | COMPLETED | ~1 day |
| 11 | [Conversations (three-pane + channel bubbles)](step-11-conversations.md) | COMPLETED | ~1 day |
| 12 | [Appointments (calendar + list)](step-12-appointments.md) | COMPLETED | ~1 day |
| 13 | [Campaigns + Templates](step-13-campaigns-templates.md) | COMPLETED | ~1 day |
| 14 | [Workflows + Automations](step-14-workflows-automations.md) | COMPLETED | ~1 day |
| 15 | [Reviews + Reporting](step-15-reviews-reporting.md) | COMPLETED | ~½ day |
| 16 | [Integrations + Billing](step-16-integrations-billing.md) | COMPLETED | ~1 day |
| 17 | [Settings (all tabs) + Notifications + Profile](step-17-settings-notifications-profile.md) | COMPLETED | ~1 day |
| 18 | [Small pages sweep (calls, catalog, activities, tasks, walk-ins, custom-fields, standard-fields, ai, staff, whatsapp, services)](step-18-small-pages-sweep.md) | COMPLETED | ~1 day |

### Track 5 — Auth + admin + polish

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 19 | [Accounts (login / register / 2FA / forgot / reset / onboarding) realign](step-19-accounts-realign.md) | Pending | ~1 day |
| 20 | [Admin panel visual refresh (scope override)](step-20-admin-refresh.md) | Pending | ~1 day |
| 21 | [Error + Access Denied + shared micro-pages](step-21-error-pages.md) | Pending | ~¼ day |
| 22 | [Polish pass + a11y audit + reduced-motion check](step-22-polish-a11y.md) | Pending | ~½ day |

**Total: ~15–18 working days.** Steps 1–7 are hard blockers for everything after them (page steps depend on tokens + shell + primitives). Steps 8–18 can run in any order once foundations land; Track 5 closes.

## Dependencies

- No external dependency beyond adding `@fontsource-variable/inter`, `@fontsource-variable/inter-tight`, `@fontsource-variable/jetbrains-mono` to `APP/package.json` (Step 1).
- **`ThemeService` migration** (Step 2) is the one step that touches shared behavior — the Tailwind darkMode selector switches from `.dark-theme` (body class) to `[data-theme="dark"]` (html attribute). Every existing `dark:` variant on a Tailwind class keeps working; every SCSS selector that reads `.dark-theme` will need a one-line swap.
- No backend changes. No migrations.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| **Tailwind is the styling framework** (CLAUDE.md stack lock) | Every new class is a Tailwind utility; SCSS is used only for the token layer + Material overrides that Tailwind can't reach |
| **Semantic tokens over raw hex** | Every new class in `features/user/**` uses `bg-surface` / `text-muted` / `border-subtle` / etc. — never `bg-white` or `#0B0C0E` |
| **No FOUC** | Inline pre-hydration `<script>` in `index.html` sets `data-theme` on `<html>` before Angular boots |
| **Reduced motion respected** | Global `@media (prefers-reduced-motion)` disables all animations + transitions |
| **`core/` never imports from `packs/`** (CLAUDE.md rule 1) | Preserved — this track doesn't touch cross-module imports |
| **Step size ≤ 10 files / ≤ 400 lines** (CLAUDE.md rule 8) | Every step below fits; page-heavy steps are split by module |

## What this track does NOT do

- Does not change the sidebar's **menu registry** or any module's registration logic (rule 5) — only the rail's *visual chrome*.
- Does not change any permission-key wiring (rule 6).
- Does not remove Angular Material — Material components (dialogs, menus, form fields) stay in place, restyled via `.mat-mdc-*` overrides that target the new tokens. Rip-out is a future follow-up.
- Does not add new routes, dashboards, KPI widgets, or empty-state copy — only restyles what exists.
- Does not touch backend audit / analytics events triggered by UI actions.
