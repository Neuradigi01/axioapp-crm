# Pricing and Billing

A focused track for subscription plans, trial lifecycle, entitlement enforcement, payment integration, and the in-app billing surface. Sits outside the numbered phase tree — vertical-neutral, picked up after Phase 5 lands the Core CRM v1 features that will be gated.

## Plan structure (locked)

Model B — bundle + matching-rate overage (Notion Teams / Linear Standard pattern).

| Plan | Monthly bundle | Includes | Extra seat / mo | Annual (-20%) | Extra seat / mo (annual rate) |
|---|---|---|---|---|---|
| **14-day Trial** | $0 | up to 3 seats | n/a | — | — |
| **Basic** | **$60/mo** | 5 seats | +$12 | $48/mo equiv ($576/yr) | +$10 |
| **Standard** | **$145/mo** | 5 seats | +$29 | $116/mo equiv ($1,392/yr) | +$23 |
| **Enterprise** | **$295/mo** | 5 seats | +$59 | $236/mo equiv ($2,832/yr) | +$49 |

**Trial = Basic features for 14 days** (founder decision; not industry default — see _Open decisions_ below for the reasoning context).

**Day-15 behaviour:** if not converted, the subscription transitions through `read_only` (30 days; login + view + export OK, no writes) → `archived` (90 days; login disabled, data retained) → permanent delete.

**Currency:** USD only for v1. INR can be added as a follow-up by extending `plans.yaml` with a `currency` axis — not in scope here.

## Feature differentiation

Per-feature placement across the four tiers is defined in `api/src/app/core/billing/plans.yaml` (created in Step 1). The full live matrix lives there and is the source of truth for what the entitlement service grants. A high-level summary of the upgrade-driver moments:

| Jump | What forces the upgrade |
|---|---|
| **Trial → Basic** | Trial expires at day 15; mutating actions stop. Must pick a paid plan to continue working. |
| **Basic → Standard** | Need **automation**, **WhatsApp / unified inbox**, **email integration**, **Google + Meta Ads webhooks**, **call recording**, **unlimited custom fields**, **public API**, **campaigns**. |
| **Standard → Enterprise** | Need **SSO**, **audit log**, **multi-branch**, **white-label**, **AI lead scoring**, **offline conversion sync**, **unlimited API**, **dedicated support**. |
| **Seat overage at any tier** | Customer grows past the 5 seats included. Each additional seat billed at the tier's overage rate. |

## Why this exists

Today, every org has equal access to every feature. There is no concept of:

| Gap | What's missing today |
|---|---|
| **Subscription per org** | No `subscriptions` table. No notion of plan, status, trial dates, billing cycle, or seats purchased. |
| **Trial lifecycle** | New orgs land with full access forever. No expiry, no read-only mode, no archive. |
| **Server-side feature gating** | Every endpoint is open to every org. No way to lock "automation" behind Standard. UI-hiding is theatre — anyone hitting the API directly gets through. |
| **Usage caps** | Contacts, leads, automation runs, API calls — all unbounded. A free trial that runs 100k automation actions burns real money. |
| **Payment + invoicing** | No payment provider integration. No checkout. No invoices. No webhook handler. |
| **In-app upgrade surface** | No `/pricing` page. No billing settings page. No way for an Owner to see what plan they're on, change it, or pay. |
| **Billing emails** | No "trial expires in 3 days," no "payment succeeded," no "card declined." |
| **Owner-only billing access** | No RBAC scoping for billing actions — today, any user with `settings.read` would see billing if it existed. |

To ship the Core CRM as a SaaS that can be self-served from a `/pricing` page, every one of those gaps needs to close — server-side first, then in the UI.

## What this does NOT do

- Does not add per-user pricing in addition to seat bundles. Model B (bundle + overage at same rate) is locked.
- Does not implement INR pricing. USD only for v1; the schema is currency-aware so INR can be added later.
- Does not implement multi-currency invoicing within a single org.
- Does not implement metered billing for AI / SMS / WhatsApp credits — those are add-ons, out of v1 scope.
- Does not implement enterprise contract pricing flows (Salesforce CPQ-style).
- Does not implement Razorpay integration. Stripe only for v1; the `PaymentProvider` interface leaves room for a future Razorpay implementation.
- Does not implement white-label billing pages (Enterprise feature, deferred).
- Does not add usage-based pricing (per-API-call billing). Caps are hard, not metered.
- Does not implement refund flows in-product — refunds handled manually via Stripe Dashboard for v1.
- Does not implement seat-removal proration. Removing seats keeps the higher seat count until next renewal, then enforces the new cap.
- Does not implement an in-app discount / coupon entry. Coupons applied via Stripe Checkout's built-in promo code field.
- Does not implement the Furniture Pack pricing. That is a separate concern layered on top of Core CRM pricing (different SKU bundles via `pack.yaml` integration).

## Open decisions (resolve at step kickoff, with defaults baked in)

| Decision | Default if not resolved | Resolved by |
|---|---|---|
| Credit card required to start trial? | **No card** (lower signup friction, Indian SMB pattern) | Step 6 |
| Payment provider | **Stripe** for v1 (Razorpay-ready abstraction) | Step 11 |
| Trial UI: hide Standard features or show them locked? | **Locked tiles with "Upgrade" CTA** (visible upgrade lever) | Step 18 |
| Enterprise: published price or "Contact Sales"? | **Published $295/mo** for v1; can hide later | Step 14 |
| Overage seat treatment on downgrade | **Keep until renewal, then enforce cap** (no mid-period lockout) | Step 9 |
| Trial: how many seats? | **3** during trial; locks to 1 on read-only mode | Step 6 |
| Annual discount % | **20%** (Pipedrive/Freshsales standard band) | Step 1 |

## Acceptance criteria

A brand-new visitor lands on the public `/pricing` page, picks a plan, and can:

1. **Sign up** at `/accounts/register` → land in a fresh org with a 14-day trial active, with Basic features unlocked and Standard features visible-but-locked.
2. **See a persistent trial banner** showing days remaining and a one-click "Upgrade now" CTA.
3. **Visit `/user/settings/billing`** (Owner only) → see current plan, trial countdown, included vs used seats, and a list of invoices (empty during trial).
4. **Hit an entitlement wall** when trying to use a Standard-only feature (e.g. opens Automation builder during trial) → in-app "Upgrade to Standard" overlay rendered, API returns `402 Payment Required` if hit directly.
5. **Hit a usage cap** when adding the 501st contact on trial → `402` with a clear "Upgrade your plan to add more contacts" body.
6. **Upgrade by clicking the banner** → redirected into Stripe Checkout → on success, returns to a confirmation page; subscription row flips to `active`, plan flips to chosen tier, Standard features unlock.
7. **Add a 6th seat** on Basic → seat-management modal previews +$12/mo cost → confirms → new seat added, next invoice reflects overage.
8. **Trial expires without conversion** at day 15 → app continues to load but all mutating endpoints return `402`. Banner becomes red with "Your trial has ended" copy and Upgrade button. After 30 more days, account moves to `archived` (login disabled).
9. **Receive emails** at: trial day -3, trial expiry, payment succeeded, payment failed, seat-overage charge, plan upgraded.
10. **Every billing event** lands an audit row: `subscription.created`, `subscription.upgraded`, `subscription.downgraded`, `seats.added`, `seats.removed`, `payment.succeeded`, `payment.failed`, `trial.expired`, `subscription.cancelled`.

All without any DB-level intervention.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Plan registry + public `/plans` API](step-1-plan-registry.md) | Pending | ~½ day |
| 2 | [Subscription model + migration](step-2-subscription-model.md) | Pending | ~1 day |
| 3 | [Entitlement service](step-3-entitlement-service.md) | Pending | ~1 day |
| 4 | [API entitlement decorators](step-4-api-entitlement-decorators.md) | COMPLETED | ~½ day |
| 5 | [Usage metering](step-5-usage-metering.md) | Pending | ~1 day |
| 6 | [Trial state machine + signup hook](step-6-trial-state-machine.md) | Pending | ~1 day |
| 7 | [Subscription read API](step-7-subscription-read-api.md) | Completed | ~½ day |
| 8 | [Plan change API](step-8-plan-change-api.md) | Completed | ~½ day |
| 9 | [Seat management API](step-9-seat-management-api.md) | Completed | ~½ day |
| 10 | [Read-only / archived mode enforcement](step-10-read-only-mode.md) | Completed | ~½ day |
| 11 | [Payment provider abstraction (Stripe)](step-11-payment-provider-stripe.md) | Completed | ~1 day |
| 12 | [Checkout session endpoint](step-12-checkout-session.md) | Completed | ~½ day |
| 13 | [Stripe webhook handler + invoice records](step-13-stripe-webhooks-invoices.md) | Completed | ~1 day |
| 14 | [Public `/pricing` page](step-14-public-pricing-page.md) | Pending | ~1 day |
| 15 | [Trial banner + countdown component](step-15-trial-banner.md) | Pending | ~½ day |
| 16 | [Billing settings page (read view)](step-16-billing-settings-page.md) | Pending | ~1 day |
| 17 | [Plan upgrade flow (modal + Stripe redirect)](step-17-plan-upgrade-flow.md) | Pending | ~1 day |
| 18 | [Locked feature tile pattern](step-18-locked-feature-tile.md) | Pending | ~½ day |
| 19 | [Owner-only RBAC + billing audit events](step-19-billing-rbac-audit.md) | Pending | ~½ day |
| 20 | [Email notifications for billing](step-20-billing-emails.md) | Pending | ~½ day |

**Total: ~12–14 working days.** Each step independently verifiable; pause and report after each per rule 9.

## Dependencies

- **Phase 1.5** (users / roles / permissions schema) — required for Owner-only billing access in Step 19.
- **Phase 1.6** (JWT auth) — required for every authenticated endpoint.
- **Phase 1.7** (audit logs) — required for Step 19. `audit_logs` must be writeable.
- **RBAC, Ownership & Self-Signup track** (Step 1) — provides the new-org-on-signup hook that Step 6 attaches the trial subscription to.
- **`core/notifications` (Phase 3.x)** — required for Step 20 billing emails.
- **`core/billing/invoice`** (existing module for customer-facing invoices the seller generates) — this is **different** from subscription invoices we generate for our own billing. Keep them clearly separated; this track creates `app/core/billing/subscription_invoices.py` (or similar) to avoid name collision.
- **Phase 5 Core CRM v1** — recommended to land first. Without Standard features (automation, conversations, campaigns, public API) actually existing, gating them is gating an empty room.

## File budget (rough)

| Area | New files | Modified files | Migrations |
|---|---|---|---|
| Backend foundation (Steps 1–6) | ~15 | ~3 | 2 (`subscriptions`, `usage_counters`) |
| Backend management (Steps 7–10) | ~8 | ~4 | 0 |
| Payment integration (Steps 11–13) | ~10 | ~2 | 1 (`subscription_invoices`) |
| Frontend (Steps 14–18) | ~18 | ~6 | — |
| Cross-cutting (Steps 19–20) | ~6 | ~10 | 0 |

**~60 files across 20 steps**, averaging 3 files per step — well within the < 10 files / < 400 lines per-step rule. Steps that touch more than 10 files (Step 13 webhook + invoice, Step 17 upgrade flow) explicitly split their scope inside the step file.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Exactly one active subscription per org | `subscriptions`: partial unique index `WHERE status IN ('trialing','active','past_due','read_only') AND org_id = ?` |
| Every gated endpoint server-side checks entitlement | `@requires_feature(...)` decorator from Step 4 wraps the route. UI-hiding alone never replaces this. |
| Caps are enforced at write time, not display time | `@enforces_cap(...)` decorator runs on the write path. Displaying a "you have 4,950 of 5,000 contacts" warning is UX, not enforcement. |
| Trial-expired orgs cannot write | Step 10 middleware short-circuits all mutating verbs (POST/PUT/PATCH/DELETE) on `read_only` orgs with a single allow-list (subscription change, logout, profile read). |
| Owner is the only role that can change plan or remove seats | Step 19 — `billing.manage` permission key is granted to Owner only by default; not editable on the Owner row. |
| Audit events are write-best-effort | Failure to write an audit row never breaks the parent billing action (per existing Step 1.7 contract). |
| Webhook handler is idempotent | Stripe redelivers events. Step 13 dedupes by `stripe_event_id` (unique constraint) and silently returns 200 on replay. |
| Plan registry is the single source of truth | `plans.yaml` defines features + caps + prices. The DB carries one row per active subscription pointing to a `plan_code`. Changing a plan's price mid-flight requires a versioning bump in `plans.yaml`, not a direct DB edit. |

## Self-check against the 10 rules

- ✅ **Rule 1:** `core/` never imports `packs/`. All scope is in `core/billing/`, `core/auth/`, `core/notifications/`, `core/audit/` — vertical-neutral.
- ✅ **Rule 2:** New tables (`subscriptions`, `subscription_invoices`, `usage_counters`) all carry `org_id` UUID FK + RLS. Stripe-side identifiers (`stripe_customer_id`, `stripe_subscription_id`) are columns on `subscriptions`, not separate tables.
- ✅ **Rule 3:** Custom-fields layered model untouched. The plans config is YAML, not custom fields.
- ✅ **Rule 4:** New forms (pricing page card grid, upgrade modal, seat editor) render statically from the plan registry — these are core schema fields, not custom-field-bearing entities.
- ✅ **Rule 5:** Sidebar registry unchanged. The `Billing` settings tab is added through the existing settings registry pattern.
- ✅ **Rule 6:** Permission registry extended with `billing.manage` and `billing.read` keys, registered via the existing module-registry pattern in Step 19. Not a new module type.
- ✅ **Rule 7:** `pack.yaml` untouched. The plans config is a separate file (`core/billing/plans.yaml`) for Core CRM pricing. Furniture-pack pricing, when added, lives in `packs/furniture/pricing.yaml` and is composed on top — not mixed in.
- ✅ **Rule 8:** Each step verifiable in < 30 min. Where any step approached the limit (Step 13, Step 17), it's split internally into clear sub-tasks within the same file.
- ✅ **Rule 9:** Stop-and-report after every step.
- ✅ **Rule 10:** No TODOs. The Razorpay-ready abstraction is deliberate scope (interface only, not stub); the Stripe implementation is real and complete.

## After this track

- The Core CRM is **fully self-served**: a stranger lands at `/pricing` → picks a plan → signs up → uses the 14-day trial → upgrades through in-app Stripe Checkout → pays month after month, all without any human intervention from our side.
- Every Standard-tier feature has a server-side entitlement check, so the *same* codebase ships as Free trial / Basic / Standard / Enterprise without duplication or feature flags.
- The Furniture Pack pricing can be layered on top by:
  - Adding `furniture-basic`, `furniture-standard`, `furniture-enterprise` plan codes to `plans.yaml` (or a separate `packs/furniture/pricing.yaml` composed at install time)
  - The same entitlement service grants pack features when the org's subscription points to a `furniture-*` plan
- Razorpay can be added as a second `PaymentProvider` implementation in ~1 step once Indian payments are needed — the abstraction is in place from Step 11.
