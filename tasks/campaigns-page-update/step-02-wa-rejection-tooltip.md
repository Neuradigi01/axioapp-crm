# Step 02 — WhatsApp rejection reason tooltip (library + picker)

**Goal:** Wherever a WhatsApp template badge shows "Rejected", hovering the badge surfaces Meta's rejection reason inline in the CRM. Users never need to open Meta Business Manager to know why a template can't be sent.
**Track:** Campaigns page update — WhatsApp UX
**Status:** Pending
**Depends on:** Step 01 (picker rows already render the badge)

Screen references in [`preview.html`](preview.html):

- **Screen 2 · Template Library** — `discount_promo` row: hovering the red `● Rejected` chip shows a tooltip with the Meta rejection reason.
- **Screen 3 · Create Campaign — WhatsApp** — same tooltip behaviour on the disabled Rejected row in the picker.

---

## Scope

Frontend only. Backend already:

- Stores `WhatsAppTemplate.rejection_reason` (populated by the Meta webhook handler at `apply_template_status_update()` in `integrations/whatsapp/templates_service.py`).
- Returns it on the `/templates/{id}/external-status` endpoint (`ExternalStatusResponse` in `templates/router.py`).
- The library list page already receives `external_rejection_reason` on the `TemplateRead` payload.

What changes: the `<template-status-badge>` component grows an optional tooltip slot, and both the library list + campaign picker pass the rejection reason into it when the status is `rejected`.

## Backend

**No changes.** Confirm during implementation that the `TemplateRead` response payload includes `external_rejection_reason` for WhatsApp rows. If it doesn't, add it to the schema — one field, one line — otherwise this step has zero backend work.

## Frontend

### Component change — `template-status-badge`

Extend the existing component (`app/src/app/features/user/core/templates/template-status-badge.component.ts`):

- Add `@Input() rejectionReason?: string`.
- When `status === 'rejected'` **and** `rejectionReason` is non-empty, render a tooltip on hover / focus.
- Tooltip content: a zinc-900 background card, ~240px wide, positioned above the badge with a downward-pointing arrow. Two lines: bold header "Meta rejection reason", body = the reason string, muted footer "Update the template and resubmit."
- Tooltip appears on `mouseenter` + `focus`, hides on `mouseleave` + `blur`. No JS positioning library — use pure CSS `position: absolute` + `translateX(-50%)`. Match the mockup at `preview.html` (`.tooltip` class).
- Accessible: badge gets `role="button"` + `tabindex="0"` when tooltip is present; tooltip has `role="tooltip"` and `aria-live="polite"`.
- Non-rejected states render exactly as today (no tooltip, no aria change).

### Usages — wire the input

- **Template library list** ([`templates.page.html`](../../app/src/app/features/user/core/templates/templates.page.html)) — pass `[rejectionReason]="row.external_rejection_reason"` alongside the existing `[status]` binding.
- **Campaign create modal picker** ([`create-campaign-modal.component.html`](../../app/src/app/features/user/core/campaigns/create-campaign-modal.component.html)) — same wiring for the picker rows delivered in Step 01.

That is the full frontend delta. No new components, no new endpoints.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/templates/template-status-badge.component.ts` | modified — add `rejectionReason` input, tooltip render + a11y wiring |
| `app/src/app/features/user/core/templates/template-status-badge.component.html` | modified — tooltip markup |
| `app/src/app/features/user/core/templates/template-status-badge.component.scss` | modified — tooltip styles (zinc-900 card, arrow, hover/focus reveal) |
| `app/src/app/features/user/core/templates/templates.page.html` | modified — pass `[rejectionReason]` |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.html` | modified — pass `[rejectionReason]` in the picker |
| `app/src/app/features/user/core/templates/template-status-badge.spec.ts` | modified or created — tooltip visibility tests |
| `api/src/app/core/templates/schemas.py` | modified **only if** `external_rejection_reason` is not already on `TemplateRead` |

**5–7 files.** Within the per-step rule.

## Tests

`template-status-badge.spec.ts`:

- Approved / pending badges — tooltip is not rendered (assert not in the DOM tree).
- Rejected badge with `rejectionReason='Missing opt-out instruction'` — tooltip hidden by default, appears on `mouseenter`, disappears on `mouseleave`.
- Rejected badge with `rejectionReason=undefined` — tooltip is not rendered (no empty tooltip flash).
- A11y — badge is focusable (`tabindex=0`) only when the tooltip is present; tooltip has `role="tooltip"`.

No integration test — the endpoint already returns the field and there's no backend logic change.

## Verification

Open **Ajay's Workspace**:

1. Create (or find) a WhatsApp template. Submit it to Meta with a body known to violate policy (e.g. `FREE!!! CLICK NOW` with no opt-out footer). Wait for Meta's webhook to flip it to Rejected — or manually seed a row for testing:

   ```sql
   UPDATE tbl_whatsapp_templates
   SET status = 'rejected',
       rejection_reason = 'Promotional wording ("FREE!!!") violates Meta URL/URN policy. Rewrite the header and resubmit.'
   WHERE id = '<template-id>';

   UPDATE tbl_message_templates
   SET external_status = 'rejected',
       external_rejection_reason = 'Promotional wording ("FREE!!!") violates Meta URL/URN policy. Rewrite the header and resubmit.'
   WHERE id = '<template-id>';
   ```

2. Go to **Templates**. Find the Rejected row → hover the red pill → tooltip appears with the rejection reason. Move mouse away → tooltip disappears.
3. Tab-focus the pill via keyboard → tooltip appears; blur → tooltip disappears.
4. Go to **Campaigns → + New Campaign → channel WhatsApp**. Open the template picker. Find the disabled Rejected row → hover the red pill → same tooltip appears.
5. Approved and Pending badges show no tooltip on hover.

## Self-check (fill in before the stop-and-report)

- 10 rules: line-by-line
- Layered architecture: frontend only (backend read from existing endpoint)
- Reuse: extended existing `<template-status-badge>` instead of building a new tooltip primitive
- Query efficiency: no new fetches — the field is already on `TemplateRead`
- Tooling: prettier + eslint on all touched files

## Awaiting your `proceed`

Done means: rejection reason shows in-app on hover in both the library list and the campaign picker, keyboard-accessible, no empty tooltips, spec suite green, browser smoke green on Ajay's Workspace. **Ship gate: WhatsApp v1 UX complete after this step.**
