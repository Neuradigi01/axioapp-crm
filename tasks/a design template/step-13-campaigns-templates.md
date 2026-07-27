# Step 13 — Campaigns + Templates refresh

**Goal:** Restyle the Campaigns module (list, builder, analytics) and the central Templates library (list, editor, category filter).
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** Pending
**Depends on:** Steps 1, 5, 6, 7

---

## AIXO patterns

### Campaigns list
- Cards grid (not a table): `auto-fit minmax(320px, 1fr)`. Card: campaign name (font-display 600 14.5px) + channel chip (WhatsApp / Email) + status pill + KPIs mini-row (mono values for Sent / Opened / Replied) + "View →" accent link.

### Campaign builder (multi-step)
- Step ribbon top: 4 dots + step labels ("Audience → Content → Schedule → Review"). Active dot = accent, past = accent-soft.
- Each step = one card, `bg-surface` `border-subtle` `rounded-2xl` p-6.
- Content step: template picker (see below) or custom message + variable-picker chips + preview panel.

### Templates library
- List page with category chips (Marketing / Transactional / Reply / Notification), search input, "+ New template" primary.
- Grid of template cards: name + channel chip + last-edited mono timestamp + preview 2 lines + "Edit →" link.
- Editor: split panel. Left = form (name / category / channel / body + variable picker). Right = live preview showing WhatsApp / Email rendered look.

### Meta template approval status
- Inline in the card + editor: pill "Approved" (emerald), "Pending" (amber), "Rejected" (red) with reason tooltip. Copy directly from the CRM UI per the campaigns-scope memory.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/campaigns/*/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/templates/*/*.{ts,html}` | modified |

**~8–10 files (split by module if it exceeds 10 — one commit per module).**

## Verification

- Campaigns list, builder, analytics all restyled.
- Templates list, editor, category filters all restyled.
- Meta approval status pill visible on template cards.

## Out of scope

- Actual template rendering engine.
- Campaign send logic.
