# Step 2: Spam + virus verdict gates in extended gate chain

**Status:** COMPLETED (2026-09-21) — `check_spam_verdict(payload)` + `check_virus_verdict(payload)` added to `core/email/quarantine/gates.py`; spam gate reads `X-Mailgun-Sflag` (case-insensitive header lookup handles the multiple parse variants Mailgun exposes) + `X-Mailgun-Sscore` and hits when `Sflag=Yes` OR score ≥ `EMAIL_SPAM_SCORE_THRESHOLD` (default 5.0); virus gate hits when `X-Mailgun-Virus` present + non-empty; both wired into `_apply_extended_gates()` in `mailgun/tasks.py` AFTER Track 5's blocklist + rate-cap, BEFORE the shipped SPF/DKIM spoof policy; **virus always beats spam** when both fire; virus verdicts land with `blocked_release=True` via Track 5's `enqueue_quarantine` (which already sets it based on reason_code); feature-flagged behind `EMAIL_VERDICT_GATES_ENABLED` (default true) — one env-var flip disables both. Smoke: `Sflag=Yes,Score=3.0`→spam; `Sflag=No,Score=7.5`→spam; empty virus header→pass; `EICAR-Test`→virus.

## Goal

Wire Mailgun's spam-score + virus-verdict headers into Track 5's extended gate chain. Verdict-hits route to quarantine with correct reason code.

## Files touched

- `api/src/app/core/email/quarantine/gates.py` — add 2 new gate functions
- `api/src/app/core/email/mailgun/service.py` — call verdict gates in chain
- `api/tests/test_verdict_gates.py`

## What this step does

- New gate `check_spam_verdict(payload) -> SpamVerdictResult`:
  - Read `X-Mailgun-Sflag` header (Mailgun says "Yes" when spam).
  - Read `X-Mailgun-Sscore` header (float score).
  - Threshold from env `EMAIL_SPAM_SCORE_THRESHOLD (5.0)`.
  - Result `spam` if `Sflag=Yes` OR `Sscore >= 5.0`. Else `pass`.
  - `reason_detail = {"flag": ..., "score": ...}`.
- New gate `check_virus_verdict(payload) -> VirusVerdictResult`:
  - Read `X-Mailgun-Virus` header.
  - Result `virus` if header present AND non-empty string. Else `pass`.
  - `reason_detail = {"virus_name": ...}`.
- Chain-order insertion (into Track 5's extended chain):
  - After blocklist + rate cap.
  - Before SPF/DKIM (verdict subsumes sender-auth in most cases).
  - Virus > spam precedence — if both, virus wins.
- Verdict hit → quarantine writer (Track 5) with `reason_code = spam_verdict | virus_verdict`; virus always `blocked_release=True`.
- Feature flag `EMAIL_VERDICT_GATES_ENABLED` — off reverts to Track 5's chain minus verdicts.

## Tests

- `test_spam_score_equal_threshold_quarantines`
- `test_spam_score_below_threshold_passes`
- `test_spam_flag_yes_quarantines_regardless_of_score`
- `test_virus_header_present_quarantines_blocked_release_true`
- `test_virus_header_empty_string_does_not_quarantine`
- `test_virus_header_absent_does_not_quarantine`
- `test_virus_wins_over_spam_when_both_fire`
- `test_verdict_gate_order_after_blocklist_before_spf_dkim`
- `test_verdict_spam_release_path_works`
- `test_verdict_virus_release_path_blocked_at_service_layer`
- `test_verdict_flag_disabled_reverts_to_track_5_chain`

## Verification checklist

- [ ] All 11 tests pass
- [ ] Pin-tests pass
- [ ] Existing mailgun-inbound + Track 5 tests still pass
- [ ] Ruff clean

## Self-check

- Rule 10: pass.
- Rule 2: pass — quarantine rows carry `org_id` per Track 5.
- Layered: pass.
- Reuse: pass — uses Track 5's quarantine writer.

## Stop-and-report

Report test pass. **Awaiting your "proceed" for Step 3.**
