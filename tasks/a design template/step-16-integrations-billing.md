# Step 16 — Integrations + Billing refresh

**Goal:** Restyle the Integrations directory + connection wizards, and the Billing module (plan cards, invoices list, seats management, upgrade modal).
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** Pending
**Depends on:** Steps 1, 5, 6, 7

---

## AIXO patterns

### Integrations directory
- Grid of provider cards: `bg-surface` `border-subtle` `rounded-xl` p-4. Content: provider logo (48px in a `bg-surface-2` `rounded-lg` square) + provider name (font-display 600 14px) + one-line description text-muted + status pill (Connected / Not connected) + "Connect →" or "Configure →" link.
- Filter chips top: All / Ads / Communication / Calendar / Payments.

### Connection wizard
- Same multi-step ribbon pattern as Campaigns builder. Steps depend on the provider (auth → mapping → test).

### Billing plans
- Grid of plan cards: `bg-surface` `border-subtle` `rounded-2xl` p-6. Content: plan name (font-display 600 18px) + price (mono 32px) + `/month` faint + feature list (checkmark rows) + primary CTA "Choose plan" or current-plan indicator.
- **Seat picker: minimum is 1** (per project memory `project_billing_min_seats.md`).

### Invoices list
- Table pattern (Step 6). Columns: date / invoice # (mono) / amount (mono) / status pill / download icon.

### Upgrade modal
- AIXO modal look (Step 7). Plan comparison side-by-side, seat picker with 1 as min, total mono, primary "Continue to checkout".

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/integrations/*/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/billing/*/*.{ts,html}` | modified |

**~8–10 files. Split if it exceeds 10.**

## Verification

- Directory grid, plan grid, invoices table all styled correctly.
- Upgrade modal seat picker allows 1 as minimum.
- Trial banner (from Step 4) still consistent with Billing plan display.

## Out of scope

- Stripe/checkout logic.
- Seat-count enforcement backend.
