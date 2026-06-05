# Step 14 — Public `/pricing` page

**Goal:** A standalone Angular route at `/pricing` (outside `/accounts` and `/user` — accessible without auth) that renders the three public plans (Basic / Standard / Enterprise) in a comparison-card layout, with monthly/annual toggle and a "Start free trial" CTA that lands in `/accounts/register`.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Step 1 (public `/api/v1/plans` endpoint). No auth dependency.

---

## Scope

One new route, one component (page), one or two child components (plan card, monthly/annual toggle), Tailwind styling. Consumes the public plans API. No backend changes in this step.

## Routing

`app/src/app/app.routes.ts` (or wherever top-level routes live) — add:

```typescript
{
  path: 'pricing',
  loadComponent: () => import('./features/pricing/pricing.page').then(m => m.PricingPage),
}
```

This sits as a peer of `/accounts/...` and `/user/...` — not inside either tree. Unauthenticated visitors can reach it.

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Logo                                            [Sign in]  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│           Simple, transparent pricing                        │
│           One CRM. Three tiers. Cancel anytime.              │
│                                                              │
│              [ Monthly ]  [ Annual — save 20% ]              │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Basic      │  │  Standard    │  │  Enterprise  │       │
│  │              │  │   POPULAR    │  │              │       │
│  │   $60/mo     │  │   $145/mo    │  │   $295/mo    │       │
│  │   5 seats    │  │   5 seats    │  │   5 seats    │       │
│  │ +$12/seat    │  │ +$29/seat    │  │ +$59/seat    │       │
│  │              │  │              │  │              │       │
│  │ ✓ Contacts   │  │ ✓ Everything │  │ ✓ Everything │       │
│  │ ✓ Leads      │  │   in Basic   │  │   in Standard│       │
│  │ ✓ Walk-ins   │  │ ✓ Automation │  │ ✓ SSO        │       │
│  │ ✓ Pipelines  │  │ ✓ WhatsApp   │  │ ✓ Audit log  │       │
│  │ ✓ Tasks      │  │ ✓ Google +   │  │ ✓ Multi-     │       │
│  │ ✓ Calendar   │  │   Meta Ads   │  │   branch     │       │
│  │              │  │ ✓ Call rec.  │  │ ✓ White-     │       │
│  │              │  │ ✓ Public API │  │   label      │       │
│  │              │  │ ✓ Campaigns  │  │ ✓ AI scoring │       │
│  │              │  │              │  │              │       │
│  │ [Start trial]│  │ [Start trial]│  │ [Start trial]│       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                              │
│  All plans start with a free 14-day trial. No credit card.   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

- Cycle toggle is reactive: prices and per-seat overage update on click.
- Annual toggle shows the per-month-equivalent ($48, $116, $236) plus "save 20%" label.
- "Most popular" badge on Standard.
- CTA → `/accounts/register?plan={code}&cycle={cycle}` so the chosen plan can flow into auto-checkout after signup.

## Component structure

```
app/src/app/features/pricing/
├── pricing.page.ts            # standalone, signal-based
├── pricing.page.html
├── pricing.page.scss          # minimal; Tailwind for everything else
├── plan-card.component.ts     # reusable card
├── plan-card.component.html
└── pricing-api.service.ts     # fetches GET /api/v1/plans
```

`pricing.page.ts`:

```typescript
@Component({
  selector: 'crm-pricing-page',
  standalone: true,
  imports: [PlanCardComponent, NgClass],
  templateUrl: './pricing.page.html',
})
export class PricingPage {
  private api = inject(PricingApiService);
  protected cycle = signal<'monthly' | 'annual'>('monthly');
  protected plans = signal<Plan[]>([]);

  ngOnInit() {
    this.api.getPlans().subscribe(({plans}) => this.plans.set(plans));
  }

  toggleCycle() {
    this.cycle.update(c => c === 'monthly' ? 'annual' : 'monthly');
  }
}
```

`pricing-api.service.ts` uses the project's existing HTTP retry interceptor (per `feedback_http_retry_interceptor` memory — new HTTP work assumes retry on transient failures for GET).

## Feature list per card

Each card displays a curated subset of the plan's features (not the full 100+ key list — that would be unreadable). The curated list per plan is **hardcoded in the frontend component**, mirroring the marketing message. Reason: full feature parity with the backend registry happens via the entitlement service at runtime; the marketing page summarises.

Curated feature lists per card:

**Basic:**
- Contacts, Leads, Walk-ins
- Pipelines (1)
- Tasks & Calendar
- Email templates (5)
- CSV import / export
- Basic dashboard
- Email support

**Standard (everything in Basic, plus):**
- Workflow automation
- Unified inbox (WhatsApp + Email + SMS)
- Google Ads + Meta Ads lead capture
- Call recording
- Email integration (IMAP/SMTP)
- Public REST API
- Email & SMS campaigns
- Advanced reports
- Chat support

**Enterprise (everything in Standard, plus):**
- SSO / SAML
- Audit logs
- Multi-branch
- White-label
- AI lead scoring
- Offline conversion sync to Ads
- Unlimited API
- Dedicated CSM + SLA

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/pricing/pricing.page.ts` | created |
| `app/src/app/features/pricing/pricing.page.html` | created |
| `app/src/app/features/pricing/pricing.page.scss` | created |
| `app/src/app/features/pricing/plan-card.component.ts` | created |
| `app/src/app/features/pricing/plan-card.component.html` | created |
| `app/src/app/features/pricing/pricing-api.service.ts` | created |
| `app/src/app/app.routes.ts` | modified — add `/pricing` route |
| `app/src/environments/environment.ts` | modified (if needed) — API base URL |
| `app/src/app/features/pricing/pricing.spec.ts` | created — unit tests |

**9 files.** Within rule.

## Tests

`pricing.spec.ts`:

- **Renders 3 cards** after API resolves.
- **Cycle toggle switches displayed prices:** monthly shows $60/$145/$295; annual shows $48/$116/$236.
- **"Most popular" badge** appears on Standard, not on others.
- **CTA URL carries plan + cycle:** clicking "Start trial" on Standard navigates to `/accounts/register?plan=standard&cycle=monthly` (or annual depending on toggle).
- **Loading state** renders skeleton until API resolves.
- **API error** renders a fallback "Pricing unavailable — please try again" with retry button.
- **Lucide icons audited:** if any `<lucide-icon name="..."/>` used, all referenced names are registered in `app.config.ts` per `feedback_lucide_icon_registry` memory.

## Smoke

```
cd app
npm run start

# In browser: http://localhost:4200/pricing
# → 3 cards visible, monthly prices shown.
# → Click "Annual" → prices flip to $48/$116/$236.
# → Click "Start trial" on Standard → navigates to /accounts/register?plan=standard&cycle=annual.
# → Lighthouse pass: page is statically renderable (no auth-gated content blocking initial paint).

# Direct unauth test:
# Open Incognito → http://localhost:4200/pricing → loads without redirect to /accounts/login.
```

## Risks

- **API down on page load.** Pricing page is the customer's first impression — graceful fallback with cached static content (Angular's build-time copy of the YAML) would be ideal. For v1, fallback is "please try again" + a static text version below. Out of scope to bake the YAML into the bundle.
- **Feature copy drift.** The curated card lists are hardcoded in the component. When `plans.yaml` adds a new flagship feature, this card list must be updated by hand. Document this contract in the component header comment: "Card feature lists are MARKETING copy, not the full entitlement set. Edit alongside plans.yaml changes."
- **PrimeNG / Material vs Tailwind.** Per CLAUDE.md, new pages use Tailwind only. The pricing page is fully new — no PrimeNG / Material imports. Verify on review.
- **Per memory `feedback_branding_crm_not_furnicrm`:** page title is "CRM" not "FurniCRM" in user-facing copy. Internal DOM classes / API contracts keep existing naming.

## Rollback

Revert the 9 files. The `/pricing` route 404s. Existing `/accounts/login` and `/user/...` trees unaffected.
