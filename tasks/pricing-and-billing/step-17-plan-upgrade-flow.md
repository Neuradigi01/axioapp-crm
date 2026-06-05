# Step 17 — Plan upgrade flow (modal + Stripe redirect)

**Goal:** A reusable upgrade modal triggered by the trial banner (Step 15) and the Billing settings page's "Upgrade plan" / "Manage seats" buttons (Step 16). User picks plan + cycle + seats → confirms → frontend hits `POST /subscriptions/checkout` (Step 12) → redirected into Stripe Checkout → on return, success page polls `GET /subscriptions/current` until status flips to `active`.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Step 12 (`/checkout` endpoint), Step 14 (plan data via public `/plans`), Step 15 (state service + banner CTA), Step 16 (billing settings buttons).

---

## Scope

Three things:

1. **Upgrade modal** — opens with plan picker, cycle toggle, seat input, "Continue to payment" button.
2. **Success / cancel landing pages** — after Stripe Checkout returns, these pages poll until the webhook has flipped the subscription state, then route to billing or show a retry.
3. **Seat-management modal (for paid subs)** — a smaller modal for in-period seat add/remove that calls `POST /subscriptions/seats`.

This step exceeds 10 files, **split into 17.a (upgrade modal + redirect) and 17.b (seat management + post-checkout landing pages)**.

## Sub-step 17.a — Upgrade modal + Stripe redirect

### Modal layout

```
┌─ Upgrade your plan ────────────────────────────────┐
│                                                      │
│  Choose your plan:                                   │
│                                                      │
│  ○ Basic — $60/mo (or $48/mo annual)                 │
│       Up to 5 seats included                         │
│                                                      │
│  ● Standard — $145/mo (or $116/mo annual)  POPULAR   │
│       Up to 5 seats included                         │
│                                                      │
│  ○ Enterprise — $295/mo (or $236/mo annual)          │
│       Up to 5 seats included                         │
│                                                      │
│  Billing cycle:                                      │
│  [ Monthly ]  [ Annual — save 20% ]                  │
│                                                      │
│  Seats:                                              │
│  [ - ]   5   [ + ]    (min 5, max unlimited)         │
│                                                      │
│  ─────────────────────────────────────────────       │
│  Estimated today:        $145.00                     │
│  Renews monthly:         $145.00                     │
│                                                      │
│       [Cancel]    [Continue to payment →]            │
└──────────────────────────────────────────────────────┘
```

### Pre-fill rules

- Plan: default to Standard (the most-popular highlight) if opened from trial banner; default to current plan if opened from Billing settings.
- Cycle: default to current cycle (or `monthly` for fresh trial).
- Seats: default to `max(included_seats, current_in_use)`.

### Estimate math

Computed client-side from plan + cycle + seats:
```
estimated_today_usd = bundle_monthly_usd if monthly else bundle_annual_usd
                     + max(0, seats - included_seats) * extra_seat_price
renews_at_usd = same recurring amount
```

### "Continue to payment" flow

1. Disable button, show spinner.
2. POST `/api/v1/subscriptions/checkout` with `{to_plan, billing_cycle, seats, success_url, cancel_url}`.
3. On 200: `window.location.href = response.checkout_url` (full-page redirect into Stripe).
4. On 400 (validation): display inline error in modal (e.g. "Cannot reduce seats below 6 — you have 6 active users").
5. On 402 (already active on this plan): show inline "You're already on this plan."

### success_url / cancel_url

```
success_url: window.location.origin + '/user/settings/billing/upgrade-success?session_id={CHECKOUT_SESSION_ID}'
cancel_url:  window.location.origin + '/user/settings/billing/upgrade-cancel'
```

Stripe substitutes `{CHECKOUT_SESSION_ID}` into the URL on redirect.

## Sub-step 17.b — Landing pages + seat management

### `/user/settings/billing/upgrade-success`

```
┌─ Payment processing ────────────────────────────────┐
│                                                      │
│             [spinner]                                │
│                                                      │
│   Hang tight — we're confirming your payment.        │
│   (Usually takes a few seconds.)                     │
│                                                      │
└──────────────────────────────────────────────────────┘
```

Polls `GET /subscriptions/current` every 2 seconds for up to 30 seconds. When `subscription.status === 'active'` and `plan_code` matches the expected, navigate to `/user/settings/billing?upgraded=true` with a green toast: "Welcome to {plan_name}!"

If 30s elapses with no update: show "Your payment was received but is taking longer than expected. Refresh this page in a minute, or check Billing settings."

### `/user/settings/billing/upgrade-cancel`

Brief page: "Upgrade cancelled. [Back to Billing] [Try again]"

### Seat-management modal

Simpler than the upgrade modal — just plan-aware seat counter + preview + "Confirm" / "Cancel."

- Opens from Billing Settings "Manage seats" button.
- Reads current `seats_purchased` and shows `[-] N [+]`.
- For increases on paid plans: button labelled "Continue to payment" (same flow as upgrade — redirects via Stripe Checkout for the prorated charge).
- For decreases: button labelled "Schedule reduction" — calls `POST /subscriptions/seats` with `outcome='scheduled'` returned; toast "Your seat count will reduce to N at next renewal."

## Files to touch

### 17.a (Upgrade modal + redirect):

| File | Action |
|---|---|
| `app/src/app/features/user/core/billing/components/upgrade-modal/upgrade-modal.component.ts` | created |
| `app/src/app/features/user/core/billing/components/upgrade-modal/upgrade-modal.component.html` | created |
| `app/src/app/features/user/core/billing/components/upgrade-modal/upgrade-modal.component.scss` | created |
| `app/src/app/features/user/core/billing/services/upgrade-modal.service.ts` | created — open/close API |
| `app/src/app/features/user/core/billing/services/billing-api.service.ts` | modified — add `createCheckoutSession()` |
| `app/src/app/features/user/core/billing/components/trial-banner/trial-banner.component.ts` | modified (Step 15 component) — wire CTA to `upgradeModalService.open()` |
| `app/src/app/features/user/core/settings/billing/components/current-plan-card.component.ts` | modified (Step 16 component) — wire button |
| `app/src/app/features/user/core/billing/components/upgrade-modal/upgrade-modal.spec.ts` | created |

**8 files.** Within rule.

### 17.b (Landing pages + seat management):

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/billing/upgrade-success.page.ts` | created |
| `app/src/app/features/user/core/settings/billing/upgrade-success.page.html` | created |
| `app/src/app/features/user/core/settings/billing/upgrade-cancel.page.ts` | created |
| `app/src/app/features/user/core/settings/billing/upgrade-cancel.page.html` | created |
| `app/src/app/features/user/core/billing/components/seat-modal/seat-modal.component.ts` | created |
| `app/src/app/features/user/core/billing/components/seat-modal/seat-modal.component.html` | created |
| `app/src/app/features/user/core/billing/services/seat-modal.service.ts` | created |
| `app/src/app/features/user/core/billing/services/billing-api.service.ts` | modified — add `changeSeats()`, `previewSeats()` |
| `app/src/app/features/user/core/settings/billing/components/seats-card.component.ts` | modified (Step 16 component) — wire Manage Seats button |
| `app/src/app/features/user/core/settings/settings.routes.ts` | modified — add upgrade-success / upgrade-cancel routes |
| `app/src/app/features/user/core/settings/billing/upgrade-success.spec.ts` | created |

**11 files.** Just over rule — defensible because of the polling-page + seat-modal natural pairing. If reviewers want stricter splitting, the seat modal can become 17.c.

## Tests

### 17.a `upgrade-modal.spec.ts`:

- **Modal opens with prefilled plan from banner CTA:** open from trial-banner → Standard pre-selected.
- **Cycle toggle updates estimate:** click Annual → estimate flips to annual amount.
- **Seat increment respects bundle min:** start at 5, click - → stays at 5, error tooltip.
- **Continue to payment hits checkout endpoint:** click button → API called with right body.
- **Successful API response triggers redirect:** mock 200 with checkout_url → `window.location.href` set (assert via spy).
- **400 validation error shown inline:** mock 400 → error message displayed, modal stays open.

### 17.b `upgrade-success.spec.ts`:

- **Polls subscription every 2s:** mount component → API called at t=0, t=2s, t=4s.
- **Stops polling and navigates on status=active:** mock returns status='active' at t=4s → router.navigate called.
- **Times out at 30s:** all polls return status='trialing' → renders timeout message at t=30s.
- **Cancel page renders try-again button:** plain page test.

### 17.b `seat-modal.spec.ts`:

- **Decrement scheduled flow:** seats=5, decrement to 4 → calls `POST /seats` → toast on success.
- **Increment paid flow:** seats=5, increment to 7 → calls `POST /seats` → redirects to Stripe.
- **Preview matches expectations:** preview API returns $24 estimate → display shows "$24.00 today."

## Smoke

```
cd app
npm run start

# As Ajay (Owner of test workspace, on trial):
# 1. Click "Upgrade" in trial banner → modal opens with Standard pre-selected.
# 2. Pick Standard, cycle=Monthly, seats=5 → click "Continue to payment."
# 3. Browser redirects to Stripe Checkout (test mode).
# 4. Pay with card 4242 4242 4242 4242.
# 5. Stripe redirects to /user/settings/billing/upgrade-success?session_id=cs_test_...
# 6. Spinner shows. Within ~5 seconds, webhook (Step 13) fires, status flips to active.
# 7. Component polls, sees active → navigates to /user/settings/billing?upgraded=true.
# 8. Green toast: "Welcome to Standard!" Banner from Step 15 disappears.

# Seat management:
# 1. From Billing settings, click "Manage seats" → seat modal opens.
# 2. Increment to 7 → preview shows "$X today, $202/mo going forward."
# 3. Click "Continue to payment" → redirects to Stripe for the prorated charge.
# 4. Pay → returns → subscription.seats_purchased updates to 7.
```

## Risks

- **Modal vs full-page choice.** A modal is more friction than a dedicated `/upgrade` page, but keeps context. For v1, modal is fine. If conversion data later shows modal is the drop-off point, switch to a page.
- **Poll timeout of 30s may be aggressive.** Stripe webhook latency varies; if it consistently takes 20s, users will see flicker. Tune in beta. The component already shows a graceful "try again" path.
- **Race: user opens upgrade modal twice quickly.** Both POSTs create separate Checkout Sessions; only the first one's `pending_checkout_session_id` persists (each call overwrites). Both URLs are valid; user follows whichever they click. Acceptable.
- **`window.location.href` redirect breaks the SPA.** That's intentional — Stripe Checkout is a separate hosted experience. After payment, we return to a fresh Angular app load (no preserved state). The success page re-fetches everything.
- **Per-memory `feedback_http_retry_interceptor`:** HTTP calls assume retry on transient failures for GETs. The polling on the success page benefits from this. POSTs should not retry on transient — checkout creation must be idempotent or fail loud.

## Rollback

Revert the 19 files across both sub-steps. The trial banner and billing page revert to having non-functional buttons (modal not opening) — they need to be reverted to "navigate to /user/settings/billing" fallback in their respective steps, or the upgrade button hidden. Communicate before rolling back.
