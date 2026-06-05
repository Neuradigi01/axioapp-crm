# Step 9 — Seat management API

**Goal:** Two endpoints — `POST /api/v1/subscriptions/seats` to add or set the total seat count, `GET /api/v1/subscriptions/seats/preview` to see the cost impact before committing. Enforces bundle minimums, in-use floors, and integrates with Stripe (Step 12) for the prorated charge.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Step 2 (subscription model — `seats_purchased`), Step 7 (read API for seat context), Step 8 (plan change shares the validation patterns). Step 12 (Stripe checkout) for the paid-add-seats flow; until then, the "needs payment" path returns the stub like Step 8.

---

## Scope

Two endpoints, the seat-math logic, and the in-use vs purchased contract. Owner-only (Step 19 enforces).

## Endpoints

### `POST /api/v1/subscriptions/seats`

Request:
```json
{ "total_seats": 8 }   // the desired total, not a delta
```

Behaviour:

- If `total_seats == subscription.seats_purchased`: `{outcome: "no_change"}`.
- If `total_seats > seats_purchased` (adding):
  - On trial: 400 — extra seats not purchasable during trial (raise included to 3 max).
  - On paid: prorated charge for the difference, charged via Stripe Checkout. Returns `{outcome: "needs_payment", checkout_url, preview: {amount_due_usd, ...}}`. Until Step 12 lands, `checkout_url=null`.
- If `total_seats < seats_purchased` (removing):
  - If `< plan.included_seats` (e.g. 4 on Basic where bundle is 5): 400 with `min_allowed: 5`.
  - If `< seats_in_use` (e.g. 5 when 6 members are active): 400 with `seats_in_use: 6, min_allowed: 6`.
  - Else: schedule for next renewal — `subscription.next_seats = total_seats`. Returns `{outcome: "scheduled", effective_at, refund_due_usd: 0}` (we do not pro-rate refunds; the customer keeps the extra seat until renewal).

### `GET /api/v1/subscriptions/seats/preview?total_seats=8`

Returns the same preview block without committing:

```json
{
  "from_seats": 5,
  "to_seats": 8,
  "delta": +3,
  "outcome_if_committed": "needs_payment",
  "amount_due_usd": 24,         // 3 extra seats * $12 * (remaining period / period length, prorated)
  "next_renewal_at": "2026-07-05T10:00:00Z",
  "monthly_cost_after_change_usd": 96,
  "annual_cost_after_change_usd": null  // null because current cycle is monthly
}
```

Used by the seat-management UI (Step 20 frontend) to show "this will cost $X" before clicking confirm.

## Backend

`api/src/app/core/billing/service.py` — add:

```python
async def preview_seat_change(session, org_id: UUID, total_seats: int) -> SeatPreview: ...

async def change_seats(session, org_id: UUID, total_seats: int,
                       payment_provider: PaymentProvider | None) -> SeatChangeResponse: ...
```

### Prorated charge math

The Stripe-side proration is what bills the customer; our preview computes a *best-effort estimate* shown in the UI:

```
delta_seats = to_seats - from_seats
extra_seat_rate = plan.extra_seat_monthly_usd  (or annual_usd / 12 if cycle=annual)
fraction_remaining = (period_end - now()) / (period_end - period_start)
amount_due_estimate = delta_seats * extra_seat_rate * fraction_remaining
```

Round to the nearest cent. Document that Stripe's invoice may differ by a few cents due to Stripe's own proration logic — the displayed amount is "approximate, your actual bill may vary by ±$0.05."

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/router.py` | modified — `POST /subscriptions/seats`, `GET /subscriptions/seats/preview` |
| `api/src/app/core/billing/service.py` | modified — `preview_seat_change`, `change_seats` |
| `api/src/app/core/billing/schemas.py` | modified — `SeatChangeRequest`, `SeatChangeResponse`, `SeatPreview` |
| `api/src/app/core/billing/lifecycle.py` | modified — handle `next_seats` in period-rollover |
| `api/tests/core/billing/test_seat_management.py` | created |

**5 files.** Within rule.

## Tests

`test_seat_management.py`:

- **No change:** request `total_seats = current` → `outcome='no_change'`.
- **Trial cannot add seats:** trial sub, request 4 → 400.
- **Trial maxes at 3:** trial allows up to 3 (set at sub creation in Step 6).
- **Adding seats on Basic:** Basic sub with 5 seats, request 8 → `outcome='needs_payment'`, preview.amount_due_estimate is positive, preview.delta=+3.
- **Removing seats above in-use and above bundle min:** Standard sub with 8 seats purchased, 6 in use, bundle 5 → request 6 → `outcome='scheduled'`, `next_seats=6`.
- **Removing below in-use:** request 5 when 6 in use → 400 with `seats_in_use=6, min_allowed=6`.
- **Removing below bundle min:** request 3 on Basic → 400 with `min_allowed=5`.
- **Preview endpoint matches commit endpoint:** call preview, then commit, compare; estimate matches actual to within ±$0.05.
- **Period-rollover applies `next_seats`:** schedule reduction, force rollover, assert seats now reduced.
- **Read-only sub CAN add seats** (it's part of the recovery path): seed read_only → request 6 → 200 needs_payment.
- **Cancelled sub cannot change seats:** 400.

## Smoke

```
docker exec template_api-api-1 pytest tests/core/billing/test_seat_management.py -v

# Preview a seat increase:
TOKEN=...
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/subscriptions/seats/preview?total_seats=8"
# → {"from_seats":5,"to_seats":8,"delta":3,"outcome_if_committed":"needs_payment","amount_due_usd":...}

# Commit the increase (until Step 12 lands, checkout_url is null):
curl -X POST http://localhost:8000/api/v1/subscriptions/seats \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"total_seats": 8}'

# Schedule a decrease:
curl -X POST http://localhost:8000/api/v1/subscriptions/seats \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"total_seats": 6}'
```

## Risks

- **Stripe proration may not match our preview.** Stripe rounds differently and applies their own day-based proration. Document the ±$0.05 caveat in UI copy.
- **Race between seat-change and user-add.** If two Admins both add a 6th user simultaneously, and seats_purchased=5, both might succeed at the user-creation step before either hits the seat cap. Mitigation: `seats_in_use > seats_purchased` is allowed transiently; daily reconciliation job (or Step 4's `enforces_cap("seats", current_provider=count_active_members)` decorator on the invite-accept route) flags the overage. Bill the overage on next invoice.
- **Adding seats on a fresh Basic in the first hour costs nearly the full $12.** That's the right answer (they're paying for a 6th seat for the full upcoming month) but feels surprising. UX copy on preview must show "$12.00 charged today, then $96/mo going forward."

## Rollback

Revert the 5 files. Any scheduled seat reductions are lost (the `next_seats` column exists from Step 8's migration; data in it is forgotten on rollback). Communicate before rolling back in production.
