# Step 9 — Template builder UI (dedicated page + multi-step wizard)

**Goal:** New dedicated page `/user/whatsapp/templates` with list view + create/edit wizard + live WhatsApp-style preview. Customer creates marketing / utility / authentication templates entirely inside Core CRM and submits for Meta approval without visiting Meta Business Manager.
**Status:** COMPLETED
**Depends on:** Step 8 (backend CRUD + submit endpoint live).

---

## Scope

In-scope:
- New route `/user/whatsapp/templates` with `whatsapp.templates.read` permission guard.
- List view component: table (name, category, language, status badge, last used count, action menu); filter chips; search; "+ Create template" button.
- Create wizard (5 steps):
  1. Basics: name, language, category (Marketing / Utility / Authentication).
  2. Header (optional): text-with-variable / image / video / document. Media upload for media headers.
  3. Body: variable-aware textarea with `{{1}}`, `{{2}}` insertion; live char count.
  4. Footer (optional): short text (60 chars max).
  5. Buttons (optional): Quick Reply (max 3) OR CTA (URL / phone) — never both.
  6. Sample values for each variable.
  7. Review + preview + submit.
- Live WhatsApp-style preview pane (right side of wizard) — looks like a real WhatsApp bubble.
- Edit (draft / rejected only): same wizard with prefilled values.
- Duplicate: opens wizard with cloned values + " (copy)" suffix.
- Delete with confirm (warn if used in active campaign).
- Inline rejection reason on rejected templates + "Edit and resubmit" CTA.

Out of scope:
- Performance card — Step 10.
- Sidebar promotion of WhatsApp module — separate step (later).

## Files to touch

| File | Action |
|---|---|
| `APP/.../whatsapp/templates/templates-page.component.ts` | **NEW** list view |
| `APP/.../whatsapp/templates/template-wizard.component.ts` | **NEW** wizard host |
| `APP/.../whatsapp/templates/wizard-steps/` (6 small components) | **NEW** per-step forms |
| `APP/.../whatsapp/templates/template-preview.component.ts` | **NEW** WhatsApp-style preview |
| `APP/.../whatsapp/templates/templates.service.ts` | **NEW** API client |
| `APP/.../whatsapp/templates/templates.types.ts` | **NEW** TS types matching Step 8 schemas |
| [`APP/src/app/features/user/user.routes.ts`](APP/src/app/features/user/user.routes.ts) | Add `/user/whatsapp/templates` lazy route |
| `APP/.../whatsapp/templates/templates-page.component.spec.ts` | **NEW** Jest |

**~9 files (6 standalone components + service + types + routes). ~700 lines.**

## Plan

1. Generate Angular standalone components per file structure above.
2. Wizard uses signal-based state; each step is a small standalone component.
3. Preview pane subscribes to wizard state signals → live re-render.
4. Service layer maps to Step 8 endpoints.
5. Permission guard on route; tab visibility per role.
6. Validation mirrors backend: char limits, button mix rule, variable count vs samples.
7. Test specs: list renders; create-flow end-to-end; rejection reason displayed.

## DB changes / migrations

**None.**

## Tests

5 Jest specs.

## Smoke

```
1. Owner navigates /user/whatsapp/templates → list renders.
2. Click "+ Create template" → wizard opens.
3. Fill marketing template with body "Hi {{1}}, sale at {{2}}." with samples.
4. Add Quick Reply buttons: Yes / No / Maybe.
5. Preview pane shows accurate WhatsApp bubble.
6. Submit → toast "Template submitted; review usually 30 min – 24 hr."
7. Status badge shows Pending.
8. Trigger Step 8's webhook simulator → status flips to Approved → toast.
9. Try to edit approved → blocked + suggests Duplicate.
10. Reject path: simulate webhook reject → reason displays inline.
11. Sales-Junior without templates.write → no "+ Create" button; list visible.
```

## Risks

- Wizard state preservation on accidental nav-away: persist to localStorage with confirm on dirty exit.
- Preview pane drift from real WhatsApp rendering — keep simple bubble, don't promise pixel-perfect.
- Media header upload to Meta uses separate resumable-upload endpoint; thin wrapper in service.

## Self-check (10 rules)

All `app/features/user/core/whatsapp/`. ✓ Rule 1. No DB. ✓ Rule 2. Custom-field engine untouched. ✓ Rule 3. Template form is Meta-spec'd, not custom-field-driven (intentional). ✓ Rule 4 N/A. New sub-route — registered via descriptor + lazy route. ✓ Rule 5. Permission read/write split. ✓ Rule 6. pack.yaml untouched. ✓ Rule 7. 9 files / ~700 lines. ✓ Rule 8 (at edge — split if needed). Stop-report. ✓ Rule 9. No TODOs. ✓ Rule 10.

## Stop & report

```
Step 9 — Template builder UI
Files: 9
Verify: end-to-end create → submit → approval → use-in-campaign without visiting Meta dashboard.
Tests: 5 Jest specs.
Next: Step 10 — per-template performance card.
Awaiting "proceed".
```
