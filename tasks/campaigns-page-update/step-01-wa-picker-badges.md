# Step 01 — WhatsApp template picker shows approval status + category + language

**Goal:** In the campaign create modal's template picker, every WhatsApp row shows an inline approval-status badge, its category (Marketing / Utility / Authentication), and its language. Non-approved rows are visually disabled and cannot be selected.
**Track:** Campaigns page update — WhatsApp UX
**Status:** Pending
**Depends on:** none (backend fields already exist)

Screen reference: **Screen 3 · Create Campaign — WhatsApp** in [`preview.html`](preview.html) — the picker with per-row `● Approved` / `● Pending review` / `● Rejected` badges plus `Marketing · en_US` labels underneath the template name.

---

## Scope

Frontend only. The backend already:

- Returns `external_status`, `category`, `language` on the `TemplateRead` schema (`api/src/app/core/templates/schemas.py`).
- Filters the `/templates?channel=whatsapp&external_status=approved` query the picker sends today (see [`create-campaign-modal.component.ts`](../../app/src/app/features/user/core/campaigns/create-campaign-modal.component.ts) around line 487–488).
- Exposes `<template-status-badge>` at [`template-status-badge.component.ts`](../../app/src/app/features/user/core/templates/template-status-badge.component.ts) with the green / amber / red visual for `approved` / `pending` / `rejected`.

What changes: the picker dropdown UI, not the underlying query or badge component.

**Important scoping decision** — the current filter drops non-approved WhatsApp templates from the response entirely. This step **broadens the query** to also return `pending` and `rejected` templates for WhatsApp, so users can see them in the picker (disabled, with the reason) instead of them silently disappearing. Non-approved rows are visibly disabled; the select action ignores them.

## Backend

**No schema changes.** One small query change:

- [`create-campaign-modal.component.ts`](../../app/src/app/features/user/core/campaigns/create-campaign-modal.component.ts) — remove the hard-coded `external_status=approved` filter on the WhatsApp branch. Send `channel=whatsapp` only. The list-templates endpoint already returns `external_status` per row.
- Server-side guard already exists: `_validate_template_channel_match` in [`campaigns/service.py`](../../api/src/app/core/campaigns/service.py) rejects non-approved WhatsApp templates on campaign create. Confirm it still does — no code change needed, but the test in this step must assert it.

## Frontend

Rebuild the template dropdown inside the create-campaign modal so each row renders:

```
┌──────────────────────────────────────────────────────────┐
│ welcome_offer                            ● Approved     │
│ Marketing · en_US · Hi {{1}}, welcome to our store!      │
├──────────────────────────────────────────────────────────┤
│ abandoned_cart                    ● Pending review      │ ← disabled
│ Utility · en_US · Hi {{1}}, forgot something?            │
├──────────────────────────────────────────────────────────┤
│ discount_promo                         ● Rejected       │ ← disabled
│ Marketing · en_US · FREE OFFER for {{1}}!                │
└──────────────────────────────────────────────────────────┘
```

Rules:

- Row shows: template `name` (bold), status badge (right-aligned), and one muted subtitle line of `<category> · <language> · <body preview>` truncated to ~80 chars.
- Use the existing `<template-status-badge [status]="row.external_status">` — do not build a second badge.
- Non-approved rows: `opacity-70`, `cursor-not-allowed`, click is a no-op, keyboard select skips them.
- Zinc palette per Core CRM: white background, `border-zinc-200`, hover `bg-zinc-50` on approved rows only.
- No blue. Selected row uses `bg-zinc-50` + `ring-1 ring-zinc-900`.
- Non-WhatsApp channels (Email) render the plain existing picker — this step only changes the WhatsApp branch.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.ts` | modified — drop `external_status=approved` from the WhatsApp fetch; expose `disabledFor(row)` helper |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.html` | modified — rebuild the template list rendering block with the new row structure |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.scss` | modified — disabled-row styles, hover, ring |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.spec.ts` | modified — unit tests for the three status variants + disabled behaviour |

**4 files.** Well within the per-step rule.

## Tests

`create-campaign-modal.spec.ts`:

- Three-template fixture (approved / pending / rejected) — all three render in the DOM.
- Approved row: click sets `templateId`.
- Pending row: click does nothing, `templateId` stays null.
- Rejected row: click does nothing, `templateId` stays null.
- Category + language + preview render for each row.
- Non-WhatsApp channel (email) does not go through this code path (asserts on selector visibility).

No backend test needed here — Step 02 covers the tooltip; Step 03 covers Email; server-side rejection of non-approved WhatsApp templates is already covered by the existing `test_campaigns_create.py` (rerun to confirm nothing regressed).

## Verification

Open the browser at **Ajay's Workspace** (`41f9ede9-…`):

1. Ensure at least three WhatsApp templates exist in the library — one Approved, one Pending, one Rejected (create + re-submit if missing).
2. Go to **Campaigns → + New Campaign**. Choose channel = WhatsApp.
3. Open the template picker. Confirm all three templates appear, each with:
   - Correct status pill (green Approved / amber Pending / red Rejected)
   - `<category> · <language> · <body preview>` subtitle
4. Click the Approved row → row highlights, template selected in state.
5. Click Pending → nothing happens.
6. Click Rejected → nothing happens.
7. Change channel to Email → picker reverts to the plain existing behaviour (no status pills).

## Self-check (fill in before the stop-and-report)

- 10 rules: `pass` / `fixed` / `N/A` line-by-line
- Layered architecture (frontend only in this step): `N/A` — no backend changes
- Reuse: `<template-status-badge>` reused; no duplicate badge added
- Query efficiency: same single `/templates` call, no per-row queries
- Tooling: prettier + eslint run on all four touched files

## Awaiting your `proceed`

Done means: the picker shows badges + category + language + preview per row, disabled non-approved rows can't be selected, prettier + eslint + spec suite pass, browser smoke green on Ajay's Workspace.
