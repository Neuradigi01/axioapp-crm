# Step 4 — Header + trial banner + command palette shell

**Goal:** Restyle the top header to AIXO's thin variant (52px), migrate the existing trial banner to the AIXO strip look, and land the Cmd+K command palette shell (empty results OK for this step — real search wiring is a future step).
**Track:** Design Refresh — Track 2 (App shell)
**Status:** Pending
**Depends on:** Step 1, Step 2, Step 3

---

## AIXO reference

- **Header:** 52px tall, `bg-surface`, 1px bottom `border-subtle`. Layout: left = collapse-rail button (only visible on desktop), middle = flex-1 with a Cmd+K "search / jump to..." pill (max-width 480px, centered on desktop, hidden on mobile), right cluster = theme toggle · notif bell · avatar menu (34px square, `bg-accent-soft` `text-accent` `border-subtle` `rounded-lg` 9px).
- **Trial banner:** 36px tall strip above the header (or between header and main). `bg-accent-soft`, 1px bottom `border-subtle`, 13px text: "You're on the **Growth trial** — {days} days left." + `Upgrade →` link right-aligned + × dismiss button. Only renders when subscription is on trial.
- **Notif dropdown:** on bell click, popover from top-right of the button. `bg-surface-2` `border-subtle` `rounded-xl` 12px, `shadow-elevated`, width 320px. Header row "Notifications" (font-display 600 14px) + dot count. List of `notification-item` rows (12px vertical padding, hover `bg-surface`). Footer "View all activity" button.
- **Avatar menu:** 224px popover. Header block: name (13px 600) + email (12px text-faint). Divider. Rows: Profile / (Settings link if not in header) / Log out (red).
- **Command palette:** overlay dialog centered top-¼ of viewport. `bg-surface-2` `border-subtle` `rounded-2xl` 14px, `shadow-elevated`, width 640px. Top: 44px input with search icon left. Body: results list. Footer: kbd hints ("↑↓ navigate · ↵ open · esc close"). For this step, results list = empty state or the same set of quick-actions the existing quick-add FAB offers.

## Scope

1. Rebuild [`header.component.html`](../../APP/src/app/features/user/core/layout/header.component.html) and `.ts` — new layout, semantic tokens, theme toggle (from Step 2) already present.
2. Migrate the existing `TrialBannerComponent` in [`billing/components/trial-banner/`](../../APP/src/app/features/user/core/billing/components/trial-banner/) to the AIXO strip look. Keep the existing signal-driven conditional rendering.
3. Restyle the `UpgradeModalComponent` link target — modal itself is polished in Step 7 (dialogs).
4. Restyle the notifications dropdown that already exists (or add if missing). Its data source (notifications API / signal) is untouched.
5. **New** — `CommandPaletteComponent` under [`user/core/shared/command-palette/`](../../APP/src/app/features/user/core/shared/). Registered globally in the shell. `Cmd+K` / `Ctrl+K` opens; `Esc` closes. Results list = static placeholder for this step (list of pages the user can navigate to, sourced from the sidebar registry).
6. Restyle avatar menu (currently a `mat-menu`) — likely stays as `MatMenu` with `.user-menu-panel` overrides pointed at new tokens. Content markup swapped to semantic tokens.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/layout/header.component.html` | modified — new markup |
| `APP/src/app/features/user/core/layout/header.component.ts` | modified — Cmd+K host binding, palette open state |
| `APP/src/app/features/user/core/billing/components/trial-banner/trial-banner.component.{html,ts}` | modified — AIXO strip look |
| `APP/src/app/features/user/core/shared/command-palette/command-palette.component.{ts,html}` | **created** |
| `APP/src/app/features/user/core/notifications/notifications-dropdown.component.{ts,html}` | modified (or created if not present) — new look |
| `APP/src/styles.scss` | modified — `.user-menu-panel` overrides refreshed for new tokens |

**7–9 files.**

## Verification

- Header is 52px tall in both themes.
- Trial banner appears when in trial state; AIXO strip look; dismiss button hides banner for the session (existing behavior).
- Cmd+K opens the palette overlay; Esc closes; click outside closes.
- Notif bell → dropdown renders with correct look.
- Avatar menu → correct look, logout still works.

## Out of scope

- Real Cmd+K search results wiring — placeholder OK.
- Notif backend rewiring — visual only.
- Quick-add FAB refresh — Step 7.
