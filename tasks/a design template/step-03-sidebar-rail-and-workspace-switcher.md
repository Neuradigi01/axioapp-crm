# Step 3 — Sidebar rail + workspace switcher

**Goal:** Rebuild the left sidebar to match AIXO's rail: collapsible width, workspace-switcher card on top, section-grouped nav in the middle, profile at bottom. Zero changes to the menu registry or permission gates.
**Track:** Design Refresh — Track 2 (App shell)
**Status:** COMPLETED — sidebar rebuilt to AIXO rail with workspace switcher on top, module list in the middle, profile card at bottom. Uses semantic tokens (`bg-surface`, `border-subtle`, `bg-accent`, `text-muted`, `text-faint`). Registry consumption + collapse/expand + mobile drawer preserved. `ng build` green.
**Depends on:** Step 1, Step 2

---

## AIXO reference

- **Expanded:** 264px wide. **Collapsed:** 68px (icon-only). Smooth `width .18s ease` transition.
- Top: workspace pill (accent-colored 28px square with initial → workspace name (font-display 600, 14px) + category label (11px, text-faint)) + chevron. Click opens a popover with category-switcher + "Replay onboarding" + "Log out".
- Middle: sections rendered from a registry. Section headings are 11px uppercase `letter-spacing:.02em` `text-faint`. Each nav item is a full-width button with `border-radius: 24px` (pill), 5px 7px padding, gap-3 flex, 13.5px, hover `bg-surface-2`, active `bg-accent-soft` + `color-accent`.
- Item badge (unread count): `font-mono` 11px pill, `bg-accent-soft` `text-accent`, right-aligned inside the pill.
- Bottom: profile card mirroring the workspace switcher.

## Scope

1. Rebuild [`APP/src/app/features/user/core/layout/sidebar.component.html`](../../APP/src/app/features/user/core/layout/sidebar.component.html) and [`sidebar.component.ts`](../../APP/src/app/features/user/core/layout/sidebar.component.ts) with Tailwind semantic tokens (`bg-surface`, `border-subtle`, `text-muted`, etc.).
2. Preserve the existing menu-registry consumption (`inject(SidebarRegistry)` or however the current code composes items) — no changes to what items appear or in what order.
3. Preserve all `[routerLink]`, `[routerLinkActive]`, permission-gated `*ngIf` bindings.
4. Preserve the existing collapse/expand behavior + `SIDEBAR_STORAGE_KEY` persistence.
5. Workspace switcher popover: for now, a static "Core CRM" label + "Log out" and "Profile" links (matching current profile menu). Multi-workspace switching is out of scope — the popover shell renders, the category list is empty state / hidden.
6. Mobile drawer variant (`mobileMenuOpen`) restyled with the same look.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/layout/sidebar.component.ts` | modified — reorganize sections/renderable model to match new structure |
| `APP/src/app/features/user/core/layout/sidebar.component.html` | modified — new markup with Tailwind semantic tokens |
| `APP/src/app/features/user/core/layout/shell.component.html` | modified — grid/flex adjustments to accommodate new rail widths + trial banner in Step 4 |

**3 files.**

## Verification

- Rail collapses/expands from the header hamburger; state persists across refresh.
- Every existing sidebar item is present, in the same order, routed to the same path.
- Owner-only / permission-gated items still hide correctly for restricted roles.
- Both dark and light themes render cleanly.
- Focus ring on nav items uses `outline: 2px solid var(--accent)`.

## Out of scope

- Actual multi-workspace switching (list of orgs, category picker) — future track.
- Sidebar registry refactor — item wiring unchanged.
- Search palette (Cmd+K) — Step 4.
