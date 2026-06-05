# Step 15 — Trial banner + countdown component

**Goal:** A persistent banner across `/user/...` routes (top of the layout shell, below the header) that, for orgs whose subscription is `trialing` or `read_only`, shows a clear "N days left in trial" / "Trial ended — upgrade now" message with a prominent Upgrade CTA. Hidden for `active` and `cancelled`.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Step 7 (`GET /subscriptions/current` — the banner data source). RBAC-Ownership (the new-signup flow that creates the trial subscription).

---

## Scope

One component, two states (active trial / expired trial), wired into the existing user-layout shell. Reads subscription via the existing app-state pattern (likely a signal-based service that fetches once on app load and caches).

## States

| Subscription status | Banner |
|---|---|
| `trialing`, `trial_days_remaining > 3` | Blue / info color. "You're on a 14-day trial. **N days left.** [Upgrade →]" |
| `trialing`, `trial_days_remaining <= 3` | Yellow / warning. "Only **N days left** on your trial. [Upgrade →]" |
| `read_only` | Red / urgent. "Your trial has ended. Upgrade to continue using CRM. [Upgrade →]" |
| `past_due` | Red. "Payment failed. Update your card to keep your subscription. [Update payment →]" |
| `active` | (no banner — hidden) |
| `archived`, `cancelled` | Red. "Your account is [archived/cancelled]. [Contact support →]" |

The Upgrade CTA opens the upgrade modal from Step 17.

## Component

```
app/src/app/features/user/core/billing/components/trial-banner/
├── trial-banner.component.ts
├── trial-banner.component.html
└── trial-banner.component.scss
```

```typescript
@Component({
  selector: 'crm-trial-banner',
  standalone: true,
  imports: [NgClass, LucideAngularModule],
  templateUrl: './trial-banner.component.html',
})
export class TrialBannerComponent {
  private subscription = inject(SubscriptionStateService);

  protected vm = computed<BannerViewModel | null>(() => {
    const sub = this.subscription.current();
    if (!sub) return null;
    if (sub.status === 'active') return null;
    if (sub.status === 'cancelled' || sub.status === 'archived') return makeFinalStateVM(sub);
    if (sub.status === 'past_due') return makePaymentFailedVM(sub);
    if (sub.status === 'trialing') return makeTrialVM(sub);
    if (sub.status === 'read_only') return makeExpiredVM(sub);
    return null;
  });

  onUpgrade() { this.upgradeModal.open(); }   // Step 17
}
```

`SubscriptionStateService` is a signal-based wrapper around `GET /api/v1/subscriptions/current` that:

- Loads once on app init (after login)
- Re-fetches on plan change events (after Step 17's checkout success returns)
- Re-fetches every 5 minutes if status is `trialing` (so the countdown stays fresh)
- Exposes `current()` signal

## Layout integration

`app/src/app/features/user/layout/user-layout.component.html` — insert the banner above the main content, below the header:

```html
<crm-app-header />
<crm-trial-banner />
<main>
  <router-outlet />
</main>
```

The banner takes 0 height when hidden (`*ngIf` removes from DOM), so `active` orgs see no layout shift.

## Tailwind styling

- Banner is full-width, ~48px tall
- Background gradient slightly more saturated than typical info bars (this is a money-asking surface, deserves attention)
- Upgrade button is high-contrast, white text on the banner's color
- On mobile: stacks message and button vertically; banner grows to ~72px

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/billing/components/trial-banner/trial-banner.component.ts` | created |
| `app/src/app/features/user/core/billing/components/trial-banner/trial-banner.component.html` | created |
| `app/src/app/features/user/core/billing/components/trial-banner/trial-banner.component.scss` | created |
| `app/src/app/features/user/core/billing/services/subscription-state.service.ts` | created — signal-based shared state |
| `app/src/app/features/user/core/billing/services/billing-api.service.ts` | created — wraps subscription HTTP calls |
| `app/src/app/features/user/layout/user-layout.component.html` | modified — insert `<crm-trial-banner />` |
| `app/src/app/features/user/layout/user-layout.component.ts` | modified — import the banner |
| `app/src/app/features/user/core/billing/components/trial-banner/trial-banner.spec.ts` | created |

**8 files.** Within rule.

## Tests

`trial-banner.spec.ts`:

- **Hidden on active subscription:** mock sub.status='active' → component renders nothing.
- **Visible on trial:** sub.status='trialing', trial_days_remaining=10 → message shows "10 days left", blue color.
- **Warning at <=3 days:** sub.status='trialing', trial_days_remaining=2 → yellow color.
- **Urgent on read_only:** sub.status='read_only' → red color, "trial has ended" copy.
- **Past_due copy:** sub.status='past_due' → "Payment failed" copy.
- **Upgrade CTA opens modal:** click button → upgrade modal service.open called.
- **Refresh on plan change:** publish a `planChanged` event → state service re-fetches → banner re-renders.
- **5-min polling on trialing:** advance time by 5 min → service has called the API again.
- **No polling on active:** advance time by 30 min on active sub → API called only once on init.

## Smoke

```
# Make sure backend is up with a trial subscription (Step 6 wired into signup).
# Sign up a fresh account via /accounts/register, log in, land at /user/dashboard.
# → Banner visible: "You're on a 14-day trial. 14 days left. [Upgrade →]"

# Force expiry to test the urgent state:
docker exec -it template_api-api-1 uv run python -c "
# UPDATE subscriptions SET status='read_only', read_only_at=now(), trial_ends_at=now() - interval '1 hour' WHERE org_id=...
"

# Refresh /user/dashboard → banner now red, "Trial has ended" copy.

# Click Upgrade → modal from Step 17 opens (if Step 17 not yet landed, falls back to navigation to /user/settings/billing).
```

Smoke targets Ajay's Workspace per ops memory.

## Risks

- **`SubscriptionStateService` is global app state.** Make sure it's `providedIn: 'root'` so the same instance is used across the banner, billing page (Step 16), and locked tiles (Step 18). Multiple instances = multiple API calls + stale views.
- **5-min polling on trial.** Cheap (one tiny API call per 5 min per active user) but worth flagging. Throttle is fine since the trial countdown only needs minute-level precision.
- **Banner z-index.** Make sure modals (Step 17) render on top, not behind the banner. Use a layout slot above the modal's root.
- **CRM branding copy.** Per memory `feedback_branding_crm_not_furnicrm`, banner text uses "CRM" not "FurniCRM."
- **Lucide icons.** Per memory `feedback_lucide_icon_registry`, any icons used (warning triangle, arrow-right) must be registered in `app.config.ts`. Audit before merging.

## Rollback

Revert the 8 files. The banner disappears from the layout; rest of the app unaffected. State service is removed, so Step 16 and Step 18 components must also revert (they depend on it) or stub their own data source.
