# Step 18 — Locked feature tile pattern

**Goal:** A reusable Angular component that wraps any "this is a Standard / Enterprise feature you don't have" surface and renders a consistent upgrade overlay. Used by the Automation builder, Conversations inbox, Reports builder, Campaigns, and any other Standard-gated UI to render an in-app upsell instead of a 402 error or a missing menu entry.
**Track:** Pricing and Billing
**Status:** Completed
**Depends on:** Step 15 (`SubscriptionStateService` — to know what plan the user is on), Step 17 (`UpgradeModalService` — clicking the CTA opens the modal). Step 1 (plan registry — to render "Standard" / "Enterprise" tier label).

---

## Scope

One reusable component + one structural directive. Two patterns of use:

1. **`<crm-locked-feature>` component** — wraps an entire route's content. Used when the whole page is Standard-only.
2. **`*crmRequiresFeature="..."` structural directive** — for inline use. Renders the gated content if entitled, else nothing (with an optional fallback template).

## The component

```html
<crm-locked-feature
  feature="automation.workflows"
  requiredPlan="standard"
  title="Workflow Automation"
  description="Automate follow-ups, lead routing, and notifications. Available on Standard and above."
  illustrationUrl="/assets/locked/automation.svg">
</crm-locked-feature>
```

Renders:

```
┌────────────────────────────────────────────────────┐
│                                                      │
│              [illustration]                          │
│                                                      │
│           Workflow Automation                        │
│                                                      │
│   Automate follow-ups, lead routing, and             │
│   notifications. Available on Standard and above.    │
│                                                      │
│              [ Upgrade to Standard → ]               │
│                                                      │
│        Already a Standard customer? Talk to support. │
└──────────────────────────────────────────────────────┘
```

### Behaviour

- Reads `SubscriptionStateService.current()`.
- If the current plan grants `feature`: the directive/wrapper does nothing — renders its projected content.
- If not: renders the locked tile.
- The plan label ("Standard") is computed from `requiredPlan` against the plan registry, or passed in directly.
- Upgrade button calls `UpgradeModalService.open({ defaultPlan: this.requiredPlan })`.

## The structural directive

```html
<!-- Wrap any content that should only show on Standard+ -->
<div *crmRequiresFeature="'automation.workflows'; else lockedTile">
  <!-- the actual feature UI -->
</div>

<ng-template #lockedTile>
  <crm-locked-feature
    feature="automation.workflows"
    requiredPlan="standard">
  </crm-locked-feature>
</ng-template>
```

Convenience shortcut — no `else` block:

```html
<!-- If the user lacks the feature, this entire block renders the standard locked tile -->
<div *crmRequiresFeature="'integrations.whatsapp'; lockedFallback: true">
  <!-- WhatsApp settings UI -->
</div>
```

Internally the directive uses the same `LockedFeatureComponent` for `lockedFallback: true`.

## Variants

Two visual variants controlled by an input:

| Variant | Use case |
|---|---|
| `'page'` (default) | Full-bleed page wrapper. The whole route is locked. |
| `'inline'` | Smaller card-like rendering. The locked feature is one section within a larger page (e.g. a Conversations tab on the inbox page). |

## Component structure

```
app/src/app/features/user/core/billing/components/locked-feature/
├── locked-feature.component.ts
├── locked-feature.component.html
├── locked-feature.component.scss
├── requires-feature.directive.ts
└── locked-feature.spec.ts
```

The directive is a standalone Angular structural directive; the component is standalone too.

## Where to register

Both are exported from `app/src/app/features/user/core/billing/index.ts` so any feature module can:

```typescript
import { LockedFeatureComponent, RequiresFeatureDirective } from '@core/billing';
```

## Asset budget

Each "locked" illustration is a small SVG (~5 KB) stored in `app/src/assets/locked/`. Initial set:

- `automation.svg`
- `whatsapp.svg`
- `campaigns.svg`
- `conversations.svg`
- `reports.svg`
- `enterprise.svg` (generic — used for SSO, audit log, multi-branch tiles)

Illustrations are not in scope to *create* — placeholder colored boxes are fine for v1; design team replaces later.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/billing/components/locked-feature/locked-feature.component.ts` | created |
| `app/src/app/features/user/core/billing/components/locked-feature/locked-feature.component.html` | created |
| `app/src/app/features/user/core/billing/components/locked-feature/locked-feature.component.scss` | created |
| `app/src/app/features/user/core/billing/components/locked-feature/requires-feature.directive.ts` | created |
| `app/src/app/features/user/core/billing/index.ts` | created — barrel exports |
| `app/src/assets/locked/automation.svg` | created (placeholder) |
| `app/src/assets/locked/whatsapp.svg` | created (placeholder) |
| `app/src/assets/locked/campaigns.svg` | created (placeholder) |
| `app/src/assets/locked/conversations.svg` | created (placeholder) |
| `app/src/assets/locked/reports.svg` | created (placeholder) |
| `app/src/assets/locked/enterprise.svg` | created (placeholder) |
| `app/src/app/features/user/core/billing/components/locked-feature/locked-feature.spec.ts` | created |

**12 files** — but 6 of them are tiny placeholder SVGs. The code surface is 6 files. Within the rule's spirit.

## Tests

`locked-feature.spec.ts`:

- **Renders nothing when entitled:** mock subscription as Standard, feature='automation.workflows' → directive shows projected content; component variant shows projected content.
- **Renders locked tile when not entitled:** subscription=Basic, feature='automation.workflows' → tile renders with title and description.
- **Upgrade CTA opens modal with prefilled tier:** click button → `UpgradeModalService.open` called with `{defaultPlan: 'standard'}`.
- **`requiredPlan` defaults from registry:** if not provided, looks up the lowest tier that grants the feature.
- **Inline variant smaller:** variant='inline' → smaller padding, no illustration.
- **Page variant full-bleed:** default variant → full padding, illustration shown.
- **`lockedFallback: true` shortcut:** directive with `lockedFallback: true` and no `else` template → renders default tile when not entitled.
- **Loading state passthrough:** subscription not yet loaded (signal returns null) → renders nothing (avoids flicker).

## Smoke

```
cd app
npm run start

# Sign in as Ajay (trial / Basic).
# Visit /user/automation (or wherever an automation builder will live — placeholder route for the smoke if not built).
# → Locked tile renders: "Workflow Automation — Available on Standard and above. [Upgrade to Standard →]"

# Click Upgrade → modal from Step 17 opens with Standard preselected.

# Force a Standard subscription:
# UPDATE subscriptions SET status='active', plan_code='standard', billing_cycle='monthly' WHERE org_id=...

# Refresh → tile gone, projected content (e.g. "Automation builder coming in Phase 5" placeholder) renders instead.
```

A real automation builder UI exists in Phase 5 — this smoke uses a placeholder until then. Test the directive against any Standard-gated feature key that has a stub page (e.g. an inbox placeholder, a campaigns placeholder).

## Risks

- **Directive misuse: forgetting the `else` template.** Without `lockedFallback: true`, no fallback renders → empty page on Basic. Document the two valid usages in the directive's docstring. Add an Angular lint rule (or code review note) if widely misused.
- **Multiple tiles on one page = visual noise.** A Conversations page that wraps three sections (WhatsApp, Email, SMS) in separate tiles is overkill. Prefer wrapping the whole page in one `page` variant when 2+ sub-features are gated together.
- **Plan label drift.** The button reads "Upgrade to Standard" — but if `requiredPlan` is wrong (e.g. typo "standrd"), the label is broken. The component validates `requiredPlan` against the plan registry at runtime and logs a console error if unknown.
- **Lucide icons** (e.g. lock icon, arrow-right) per memory `feedback_lucide_icon_registry` must be in `app.config.ts`. Audit on merge.
- **CRM branding** per memory `feedback_branding_crm_not_furnicrm` — text reads "CRM" not "FurniCRM."

## Rollback

Revert the 12 files. Any Phase 5 features that adopted the directive must wrap their content with a manual `*ngIf` check against the subscription state, or remove the gate entirely (UI-only — server-side gates from Step 4 remain in force). Track adoption.
