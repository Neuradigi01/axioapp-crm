# Step 7 — Dialogs + menus + toasts + Quick-add FAB

**Goal:** Restyle every overlay-layer primitive: modal dialogs, dropdown menus, popovers, side sheets/drawers, toasts, and the Quick-add FAB.
**Track:** Design Refresh — Track 3 (Shared primitives)
**Status:** COMPLETED — AIXO overrides landed for `.mat-mdc-dialog-container` / `.mat-mdc-menu-panel` / `.mat-mdc-snack-bar-container`; `.cdk-overlay-dark-backdrop` darkened to 60%. Global `popIn` / `fadeIn` / `toastIn` keyframes added to `aixo-tokens.scss`. ToastHostComponent, QuickAddFabComponent, ConfirmDialogComponent restyled with semantic tokens + AIXO panel look. `ReassignModalComponent` / `BulkActionBarComponent` deferred to Step 9/10 (page-context restyle). `ng build` green.
**Depends on:** Step 1

---

## AIXO reference

### Modal dialog
- Overlay: `bg-black/60`.
- Panel: `bg-surface-2`, `border-subtle`, `rounded-2xl` (14px), `shadow-elevated`, animation `popIn .12s ease` (defined in Step 1).
- Header: 20px padding, title `font-display` 600 16px, close × top-right (icon-only 34px).
- Body: 20px padding, 13.5–14px text.
- Footer: 16px padding, right-aligned button pair, gap-2.

### Side sheet / drawer
- Slides from right; width 480px (desktop) / full-width (mobile).
- Same visual language as modal (surface-2, border-subtle, no top-left rounding).

### Dropdown menu (mat-menu / custom popover)
- `bg-surface-2` `border-subtle` `rounded-xl` (12px) `shadow-elevated`, 6px padding.
- Menu item: full-width button, `rounded-lg` (8px), 9px 10px padding, 13px, gap-2 with 16px leading icon, hover `bg-surface`.
- Divider: 1px `bg-subtle` with 2px 4px margin.
- Section label: 11px uppercase `letter-spacing: .06em` `text-faint`, 6px 8px padding.

### Toast
- Bottom-right corner stack; each toast: `bg-surface-2` `border-subtle` `rounded-xl`, 13px, 12px 14px padding, `shadow-elevated`, animation `toastIn .15s ease`.
- Success: leading icon `text-emerald-400`. Error: `text-red-400`. Info: `text-accent`.

### Quick-add FAB
- Fixed bottom-right, 56px `rounded-2xl` `bg-accent` `text-white`, shadow-elevated. Icon 20px.
- On click: opens a popover (surface-2, rounded-xl, shadow-elevated) with list of quick-add actions.

## Scope

1. `.mat-mdc-dialog-container` overrides in `styles.scss` — apply AIXO panel look (already partially there for `.attachment-preview-dialog`; make it default).
2. `.mat-mdc-menu-panel` overrides — AIXO menu look.
3. Restyle `SnackBar` overrides for `MatSnackBar` used across the app — align with AIXO toast.
4. Restyle `ToastHostComponent` (used in shell) — AIXO toast look.
5. Restyle `QuickAddFabComponent` (used in shell) — AIXO FAB + popover.
6. Restyle `ConfirmDialogComponent` under [`shared/confirm-dialog/`](../../APP/src/shared/confirm-dialog/) — AIXO modal + button pair.
7. Restyle `ReassignModalComponent`, `BulkActionBarComponent`, and other shared overlay components.

## Files to touch

| File | Action |
|---|---|
| `APP/src/styles.scss` | modified — Material dialog + menu overrides |
| `APP/src/app/features/user/core/notifications/toast-host.component.{ts,html,scss}` | modified |
| `APP/src/app/features/user/core/shared/quick-add-fab/quick-add-fab.component.{ts,html,scss}` | modified |
| `APP/src/shared/confirm-dialog/confirm-dialog.component.{ts,html,scss}` | modified |
| `APP/src/shared/bulk-action-bar/bulk-action-bar.component.{ts,html,scss}` | modified |
| `APP/src/shared/reassign-modal/reassign-modal.component.{ts,html,scss}` | modified |

**~8–10 files.**

## Verification

- Open a confirm dialog anywhere in the app — AIXO panel look.
- MatSnackBar toast triggered from any save action — AIXO toast look.
- Quick-add FAB visible, opens the popover, closes on outside click.

## Out of scope

- Rebuilding dialog logic — only visual.
- Migrating away from Material's overlay CDK — future.
