# Step 16 — Billing settings page (read view)

**Goal:** A page at `/user/settings/billing` that shows the current plan, trial countdown (if applicable), seat usage, billing cycle, next renewal date, and a list of past invoices with download links. **Read-only in this step** — plan upgrade and seat management UI controls land in Step 17.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Step 7 (subscription read API), Step 13 sub-step 13.c (invoice list API), Step 15 (the `SubscriptionStateService`).

---

## Scope

One page component with several read-only sections, hooked into the settings registry as a new tab alongside the existing Profile / 2FA / Login History / Appearance tabs. Owner-only visibility (enforced visually here; Step 19 enforces server-side).

## Page layout

```
┌─ /user/settings ─────────────────────────────────────┐
│  [Profile] [2FA] [Login history] [Appearance] [Billing] │
├───────────────────────────────────────────────────────┤
│                                                        │
│  Current plan                                          │
│  ┌────────────────────────────────────────────┐       │
│  │  14-day Trial             [Upgrade plan]    │       │
│  │  12 days remaining                          │       │
│  │  Trial started 2026-06-05                   │       │
│  │  Trial ends   2026-06-19                    │       │
│  └────────────────────────────────────────────┘       │
│                                                        │
│  Seats                                                 │
│  ┌────────────────────────────────────────────┐       │
│  │  Using 3 of 3 seats           [Manage seats]│       │
│  │  Trial includes 3 seats; cannot add more    │       │
│  │  until you upgrade.                         │       │
│  └────────────────────────────────────────────┘       │
│                                                        │
│  Usage                                                 │
│  ┌────────────────────────────────────────────┐       │
│  │  Contacts                47 / 500    [9%]   │       │
│  │  ▰▱▱▱▱▱▱▱▱▱                                 │       │
│  │                                              │       │
│  │  Leads this month         12 / 50   [24%]   │       │
│  │  ▰▰▱▱▱▱▱▱▱▱                                 │       │
│  │                                              │       │
│  │  Storage                  8 MB / 100 MB     │       │
│  │  ▰▱▱▱▱▱▱▱▱▱                                 │       │
│  │                                              │       │
│  │  Emails this month        3 / 100           │       │
│  │  ▱▱▱▱▱▱▱▱▱▱                                 │       │
│  └────────────────────────────────────────────┘       │
│                                                        │
│  Payment method                                        │
│  ┌────────────────────────────────────────────┐       │
│  │  No payment method on file.                 │       │
│  │  [Add payment method] (links to Stripe      │       │
│  │   Customer Portal if customer exists)       │       │
│  └────────────────────────────────────────────┘       │
│                                                        │
│  Invoices                                              │
│  ┌────────────────────────────────────────────┐       │
│  │  Date         Amount    Status   Actions    │       │
│  │  (empty during trial — "No invoices yet")   │       │
│  └────────────────────────────────────────────┘       │
│                                                        │
└────────────────────────────────────────────────────────┘
```

## Sections (in order)

1. **Current plan card** — plan name, trial / billing-cycle context, next-renewal date, primary CTA `[Upgrade plan]` (active in Step 17). On non-trial plans: shows monthly/annual cost.
2. **Seats card** — `seats.in_use / seats.purchased`, included seats, extra-seat cost, `[Manage seats]` (active in Step 17).
3. **Usage section** — progress bars for every cap in the active plan. Bars colored green (< 50%), yellow (50–80%), red (> 80%). `is_unlimited: true` shows "Unlimited ✓" instead.
4. **Payment method** — shows last-4 + brand if a Stripe payment method is on file (read from a future call); placeholder copy during trial. `[Manage in Stripe]` button opens the Stripe Customer Portal in a new tab (link constructed via a backend helper that creates a portal session — out of scope for this step; ship the button disabled with tooltip "Available after first payment").
5. **Invoices table** — date, number, amount, status, `[Download PDF]` link to the Stripe `hosted_invoice_url`. Empty state during trial.

## Component structure

```
app/src/app/features/user/core/settings/billing/
├── billing.page.ts
├── billing.page.html
├── billing.page.scss
├── components/
│   ├── current-plan-card.component.{ts,html}
│   ├── seats-card.component.{ts,html}
│   ├── usage-bars.component.{ts,html}
│   └── invoices-table.component.{ts,html}
```

Each child component is a pure "given this data, render it" view — no HTTP calls. Data flows from `billing.page.ts` via `@Input()` signals.

## Data source

`billing.page.ts`:

```typescript
@Component({...})
export class BillingPage {
  private state = inject(SubscriptionStateService);   // from Step 15
  private api = inject(BillingApiService);

  protected subscription = this.state.current;        // signal<SubscriptionResponse | null>
  protected invoices = signal<Invoice[]>([]);

  ngOnInit() {
    this.api.listInvoices().subscribe(rows => this.invoices.set(rows));
  }
}
```

If `subscription()` is null (loading), the page shows skeletons. Errors show a "Failed to load. Retry" state.

## Route registration

`app/src/app/features/user/core/settings/settings.routes.ts` (or wherever the settings tabs are wired) — add:

```typescript
{
  path: 'billing',
  loadComponent: () => import('./billing/billing.page').then(m => m.BillingPage),
  canActivate: [permissionGuard('billing.read')],   // Step 19 contributes the guard + permission key
}
```

The tab itself appears in the settings sidebar/header based on the same permission check. Non-Owner users do not see the Billing tab.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/billing/billing.page.ts` | created |
| `app/src/app/features/user/core/settings/billing/billing.page.html` | created |
| `app/src/app/features/user/core/settings/billing/billing.page.scss` | created |
| `app/src/app/features/user/core/settings/billing/components/current-plan-card.component.ts` | created |
| `app/src/app/features/user/core/settings/billing/components/current-plan-card.component.html` | created |
| `app/src/app/features/user/core/settings/billing/components/seats-card.component.ts` | created |
| `app/src/app/features/user/core/settings/billing/components/seats-card.component.html` | created |
| `app/src/app/features/user/core/settings/billing/components/usage-bars.component.ts` | created |
| `app/src/app/features/user/core/settings/billing/components/usage-bars.component.html` | created |
| `app/src/app/features/user/core/settings/billing/components/invoices-table.component.ts` | created |
| `app/src/app/features/user/core/settings/billing/components/invoices-table.component.html` | created |
| `app/src/app/features/user/core/settings/settings.routes.ts` | modified — add `billing` route |
| `app/src/app/features/user/core/settings/components/settings-tabs.component.html` | modified — add Billing tab |
| `app/src/app/features/user/core/billing/services/billing-api.service.ts` | modified (from Step 15) — add `listInvoices` |
| `app/src/app/features/user/core/settings/billing/billing.spec.ts` | created |

**15 files.** Exceeds the per-step rule. Split into two sub-steps:

### Sub-step 16.a:
- `billing.page.{ts,html,scss}`
- `current-plan-card`, `seats-card` components
- Route + tab registration
- `billing-api.service` extension for `getSubscription` (already mostly there)
- Smoke: Current plan + seats sections render
- Test: page mounts, displays subscription summary

### Sub-step 16.b:
- `usage-bars`, `invoices-table` components
- `listInvoices` API wiring
- Full spec

Report after each sub-step.

## Tests

`billing.spec.ts`:

- **Renders trial state correctly:** subscription mock = trialing → current plan card shows "14-day Trial" + days remaining.
- **Renders active basic correctly:** Basic active → card shows "$60/mo, renews YYYY-MM-DD."
- **Seats card shows trial restriction:** trialing → "Trial includes 3 seats; cannot add more" + Manage Seats button disabled.
- **Seats card on paid:** active Basic → "Using 4 of 5 seats" + Manage Seats enabled.
- **Usage bars colors:** mock contacts 600/500 → red bar; 250/500 → yellow; 50/500 → green.
- **Unlimited usage shows "Unlimited":** Enterprise plan resources with cap=-1 → bar replaced with "Unlimited ✓".
- **Invoices empty state:** no invoices → "No invoices yet" with helper text.
- **Invoices populated:** mock 3 invoices → table with 3 rows, each with download link.
- **Permission gate:** non-Owner user → route 403 (Access Denied page from RBAC-Ownership Step 4).

## Smoke

```
cd app
npm run start

# Sign in as Ajay (Owner of test workspace).
# Navigate to /user/settings/billing.
# → Page renders. Current plan = trialing. Days remaining computed. Seats card shows 1 of 3. Usage bars all green / low.

# Force a paid state:
# UPDATE subscriptions SET status='active', plan_code='basic', billing_cycle='monthly', stripe_customer_id='cus_test', current_period_end=now() + interval '1 month' WHERE org_id=...

# Refresh → page now shows Basic plan, "$60/mo, renews YYYY-MM-DD." Seats card shows manage button enabled. Invoices table empty (still no Stripe activity).

# After completing a real test checkout (Stripe + webhook from Step 13):
# Refresh → invoices table now has one row, click Download → Stripe-hosted PDF opens.

# Permission test:
# Sign in as an Employee user → navigate to /user/settings/billing → redirected to /user/access-denied per RBAC-Ownership Step 4.
```

## Risks

- **Stripe Customer Portal link.** "Manage payment method" needs a backend endpoint to create a Stripe Billing Portal session URL. Out of scope here; ship the button as disabled with a "Coming soon" tooltip and add the endpoint as a tiny follow-up step. Document in the step report.
- **Page renders before subscription loads.** Use skeleton placeholders matching the section layout — avoids layout jump.
- **Invoices list pagination.** For v1, assume <50 invoices. No pagination. If a long-lived account exceeds that, add pagination later.
- **Permission key `billing.read` (vs `billing.manage`).** Step 19 introduces both. This step uses `billing.read` for tab visibility; Step 17's mutating actions check `billing.manage`. Read-only Owners (if such a thing) see the page but can't act — but there's no real-world case for that, so in practice the two permissions are co-granted to Owner only.

## Rollback

Revert the 15 files. The Billing settings tab disappears. Other settings tabs unaffected. State service is still used by Step 15's trial banner, so that stays intact.
