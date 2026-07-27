# Step 17 — Settings + Notifications + Profile refresh

**Goal:** Restyle the settings page (all tabs — General, Users, Roles, Permissions, Custom Fields, Standard Fields, Pipelines, Appearance, Data, Security, etc.), the notifications preferences page, and the user profile page.
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** Pending
**Depends on:** Steps 1, 5, 6, 7

---

## AIXO patterns

### Settings two-column layout
- Left sub-nav: 220px `bg-surface` `border-subtle` right. Sections grouped (Workspace / Users & Roles / Data / Appearance / Security). Item = full-width link, `rounded-lg`, hover `bg-surface-2`, active `bg-accent-soft` `text-accent`.
- Right content: max-w-880, p-6. Grouped in card sections. Each section:
  - Section title (font-display 600 15px)
  - Section description (13px text-muted, `mb-4`)
  - Card containing the form fields OR the table OR the list.

### Notifications preferences
- List of channels (Email / In-app / SMS / Push). Each row: channel name + description + toggle switch (Step 5 primitive).
- Grouped by event category (Leads / Appointments / Billing / etc.).

### Profile page
- Two cards: (1) Personal info form (name / email / phone / avatar), (2) Password + 2FA (view state; "Change password" button links to existing flow).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/settings/**/*.{ts,html,scss}` | modified |
| `APP/src/app/features/user/core/notifications/notifications-preferences/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/profile/*/*.{ts,html}` | modified |

**Settings alone has many tabs — split by tab group if needed. Aim for ≤10 files per commit.**

## Verification

- Every settings tab renders with the two-column layout.
- Appearance tab (Step 2) matches the header toggle look.
- Users/Roles/Permissions tables use the new table look (Step 6).

## Out of scope

- New settings surfaces.
- RBAC logic.
