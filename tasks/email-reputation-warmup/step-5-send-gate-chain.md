# Step 5: Send-gate chain refactor — ceiling → wallet → rate → dispatch + skip codes

**Status:** COMPLETED

## Goal

Enforce the four-gate chain on every outbound send. Distinct skip codes for support debugging. Wallet debit is optional (no-op if credits system absent).

## Files touched

- `api/src/app/core/conversations/adapters/email.py` — `send_email()` gate chain
- `api/src/app/core/email/reputation/gates.py` — 4 gate functions
- `api/src/app/core/email/reputation/skip_codes.py` — enum + human-readable
- `api/tests/test_send_gate_chain.py`

## What this step does

- `gates.py`:
  - `check_ceiling(db, org_id, envelope_type, domain_id) -> None` — raises `SkippedSendingLimit` if `daily_sent_count >= stage cap`.
  - `check_wallet(db, org_id) -> WalletDebit` — returns debit token; raises `SkippedWalletEmpty` if credits absent. No-op if wallet not configured.
  - `check_rate_limit(org_id, envelope_type) -> None` — Redis rate check `rate:send:{org_id}:{envelope_type}:{minute_bucket}`. Threshold from env. Raises `SkippedRateLimit`.
  - `check_reputation(db, org_id, envelope_type, domain_id) -> None` — reads row; if `reputation_state='blocked'` and `blocked_until > now()`, raises `SkippedReputationBlock`.
- Chain order in `send_email()`:
  1. `check_reputation` (fastest fail, no side-effects)
  2. `check_ceiling`
  3. `check_wallet` (may debit — refund on failure below)
  4. `check_rate_limit`
  5. Dispatch via Mailgun API client.
  6. On success: `incr_counter("sent"); increment_daily_sent_count(row)`.
  7. On dispatch failure: refund wallet debit; do NOT bump send counter.
- Skip-code enum: `SKIPPED_REPUTATION_BLOCK, SKIPPED_SENDING_LIMIT, SKIPPED_WALLET_EMPTY, SKIPPED_RATE_LIMIT`.
- Each skip returns to caller with structured error; campaign send loops log the code and move on.

## Tests

- `test_gate_order_reputation_first_ceiling_second_wallet_third_rate_fourth`
- `test_gate_reputation_blocked_short_circuits_no_wallet_debit`
- `test_gate_ceiling_rejects_over_daily_cap`
- `test_gate_wallet_empty_rejects_no_dispatch`
- `test_gate_wallet_refunds_on_dispatch_failure`
- `test_gate_rate_limit_rejects_over_hourly`
- `test_gate_dispatch_success_bumps_daily_and_sent_counters`
- `test_gate_skipped_codes_distinct_per_reason`
- `test_gate_wallet_no_op_when_credits_system_absent`

## Verification checklist

- [ ] All 9 tests pass
- [ ] Existing send-email smoke passes
- [ ] Pin-tests pass
- [ ] Ruff clean

## Self-check

- Rule 10: pass.
- DB efficiency: pass — one row lookup per send, one counter INCR.
- Layered: pass.

## Stop-and-report

Report file count, test pass, skip-code enum values. **Awaiting your "proceed" for Step 6.**
