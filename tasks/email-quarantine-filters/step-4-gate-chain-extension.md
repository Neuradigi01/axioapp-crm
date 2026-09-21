# Step 4: Gate-chain extension — blocklist gate + rate cap gate + reroute size/spam/virus to quarantine

**Status:** COMPLETED (2026-09-21) — new `gates.py` module in `core/email/quarantine/` ships `decide_filter_action` (allow > block precedence; address > contact-flag > domain specificity within same rule_type) + `check_sender_rate_cap` (Redis time-bucketed hourly counter; first over-cap quarantines, subsequent silently drop; fail-open on Redis outage). Mailgun Celery task (`process_mailgun_inbound` inside `tasks.py`) extended with `_apply_extended_gates()` helper — runs after sender-email + contact resolution, BEFORE SPF/DKIM spoof policy, so blocked senders never spam `sender_auth_failed` audit rows. Delivery-ID dedupe short-circuit prevents double-quarantine on retries. Extended chain drops directly to `enqueue_quarantine` service (transactions live there); on quarantine or silent drop, task returns after `_cleanup(pending_dir)`.

## Goal

Extend the shipped mailgun-inbound gate chain. Add two new gates (blocklist, per-sender rate cap). Reroute size/spam/virus rejects into quarantine rows rather than silent drop.

## Files touched

- `api/src/app/core/email/mailgun/service.py` — gate-chain refactor
- `api/src/app/core/email/mailgun/tasks.py` — quarantine writer invocation
- `api/src/app/core/email/quarantine/gates.py` — new gate functions
- `api/tests/test_extended_gate_chain.py`

## What this step does

- New `gates.py`:
  - `check_blocklist(db, *, org_id, endpoint_id, from_address) -> BlocklistResult` — reads `resolve_effective_rules()`, applies precedence (allow > block; address > contact-flag > domain). Result: `allow_short_circuit | block | pass`.
  - `check_per_sender_rate_cap(*, org_id, from_address) -> RateCapResult` — Redis `mgw:sender:{org_id}:{from_lower}:{hour_bucket}` counter. Threshold `EMAIL_INBOUND_PER_SENDER_HOURLY_CAP (20)`. Result: `pass | first_hit_quarantine | over_drop`.
- Extended chain in `handle_reply_capture` / `handle_forwarded_address`:
  1. Signature (existing)
  2. Size (existing) — on fail: quarantine `size_exceeded`
  3. Auto-submitted (existing) — unchanged
  4. Blocklist (NEW): allow-match → skip block gate; block-match → quarantine `blocked_sender`
  5. Per-sender rate cap (NEW): first hit → quarantine `rate_capped`; over → silent drop with audit
  6. Spam verdict (Track 6 wires): if verdict fires → quarantine `spam_verdict`
  7. Virus verdict (Track 6 wires): if verdict fires → quarantine `virus_verdict` with `blocked_release=True`
  8. SPF/DKIM (existing) — unchanged
  9. Attachments (existing) — unchanged
- Quarantine writer:
  - Extract from-address, subject, body_snippet (first 500 chars of body_text), attachment_summary (filenames + sizes, no content).
  - Payload MIME already on disk under `./storage/pending-inbound/{uuid}/` — move to `./storage/quarantine/{quarantine_id}/`.
  - Insert quarantine row + delete pending-inbound dir.
- Feature flag `EMAIL_QUARANTINE_GATES_ENABLED` — flip off reverts to shipped mailgun-inbound reject behavior.

## Tests

- `test_gate_blocklist_address_quarantines_message`
- `test_gate_blocklist_domain_quarantines_message`
- `test_gate_blocklist_contact_flag_quarantines_message`
- `test_gate_allowlist_beats_blocklist_at_same_kind`
- `test_gate_address_beats_contact_flag_beats_domain_within_type`
- `test_gate_per_sender_rate_cap_quarantines_at_threshold`
- `test_gate_per_sender_rate_cap_drops_silently_after_first_quarantine`
- `test_gate_size_exceeded_moved_from_reject_to_quarantine`
- `test_gate_chain_order_blocklist_before_rate_cap`
- `test_gate_payload_moved_from_pending_inbound_to_quarantine_dir`
- `test_gate_flag_disabled_reverts_to_shipped_behavior`

## Verification checklist

- [ ] All 11 tests pass
- [ ] Existing mailgun-inbound tests still pass
- [ ] Pin-tests pass
- [ ] Ruff clean

## Self-check

- Rule 2: pass — rules scoped by org.
- Rule 10: pass.
- DB efficiency: pass — 1s cache on filter rules read.

## Stop-and-report

Report test pass, gate flow diagram. **Awaiting your "proceed" for Step 5.**
