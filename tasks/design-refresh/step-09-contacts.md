# Step 9 — Contacts refresh

**Goal:** Restyle the Contacts list, detail drawer / modal, import wizard, and any contact-related overlays.
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** COMPLETED — contacts list, form modal, detail page, import wizard, and bulk-action bar all restyled with semantic tokens. List page uses `PageHeader`-style header + `.btn`/`.input`/`.select` + AIXO table. Detail + import get bulk token swap (zinc → surface/text tokens). Bulk-action bar is now the floating AIXO surface-2 pill from Step 7. `ng build` green.
**Depends on:** Steps 1, 5, 6, 7

---

## AIXO patterns to apply

- **List page** — page-header (title "Contacts" + count badge + primary "+ Add contact" button), filter chip row, search input (40px h, `bg-app` `border-subtle` `rounded-lg`, leading search icon `text-faint`, placeholder text-faint), table with row-hover actions.
- **Detail drawer** — slides from right, 520px width, `bg-surface-2` `border-subtle`. Header: avatar (accent-soft bg, initials) + name + email + close ×. Sections separated by 1px `border-subtle`: About (custom fields), Activity timeline, Related deals, Notes.
- **Bulk-action bar** — floats at bottom-center when selection > 0, `bg-surface-2` `border-subtle` `rounded-xl` shadow-elevated, actions horizontal (Assign, Tag, Export, Delete).
- **Import wizard** — full-page multi-step (Upload → Map fields → Value-map warnings → Import). Each step card. Progress ribbon at top (mono step counter).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/contacts/contacts-list/contacts-list.page.{ts,html}` | modified |
| `APP/src/app/features/user/core/contacts/contact-detail/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/contacts/import/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/contacts/**/*.scss` | modified — strip obsolete Material overrides |

**~8–10 files. Split by "list + detail" vs "import wizard" if it exceeds 10.**

## Verification

- Contacts list renders in dark + light with new table look.
- Detail drawer opens with AIXO look; sections navigable.
- Bulk-action bar appears on multi-select.
- Import wizard flows through steps with new card look.

## Out of scope

- Backend / API changes.
- Import logic — visual only.
