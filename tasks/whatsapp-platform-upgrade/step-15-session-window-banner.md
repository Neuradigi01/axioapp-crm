# Step 15 — 24-hour session window banner + WhatsApp-specific composer states

**Goal:** Make the WhatsApp 24-hour session window visible to staff. Composer disables regular text out-of-session and prominently surfaces the template picker instead. Prevents "ghosting" caused by sends Meta drops silently.
**Status:** COMPLETED
**Depends on:** Step 14 (inbox upgrades pattern).

---

## Scope

In-scope:
- Track `tbl_conversations.last_customer_message_at TIMESTAMPTZ` (add if missing); updated on every inbound webhook from contact.
- Extend `GET /api/v1/conversations/{id}` with `whatsapp_session_state: { in_session: bool, expires_at, hours_remaining }` (only when channel = WhatsApp).
- Frontend (WhatsApp conversations only):
  - In-session banner (green): "Free session — expires in 4h 12m" with minute-tick refresh.
  - Out-of-session banner (yellow): "24-hr session expired. Only approved templates can be sent." + [Pick template] CTA.
- Composer behavior:
  - In-session: regular text enabled.
  - Out-of-session: regular text input shows tooltip + disabled state; template picker prominent.

Out of scope:
- Per-agent SLA / response-time tracking — Step 20 (analytics).
- Cost preview per send — Step 21 (cost dashboard).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/conversations/models.py` | Add column if missing |
| `API/alembic/versions/<ts>_last_customer_message_at.py` | **NEW** (conditional) |
| `API/src/app/core/conversations/whatsapp_session.py` | **NEW** helper computing state |
| `API/src/app/core/conversations/adapters/whatsapp.py` | Update timestamp on inbound |
| `API/src/app/core/conversations/router.py` | Include session_state in detail response |
| `APP/.../conversations/header/session-window-banner.component.ts` | **NEW** |
| `APP/.../conversations/thread/composer.component.ts` | Out-of-session disabled state + prominent template CTA |
| `API/tests/conversations/test_session_window.py` | **NEW** |

**~8 files. ~300 lines.**

## Plan

1. Confirm column existence; backfill from last inbound message per conversation if adding.
2. Helper: `in_session = (now - last_customer_message_at) < 24h`.
3. Adapter: update timestamp atomically with inbound message insert.
4. Frontend banner: signal that re-evaluates every 60s using server timestamp.
5. Composer: signal `canSendFreeText` derived from session state.
6. Tests: state transitions at the 24-hour boundary + composer-disable behavior.

## DB changes / migrations

`tbl_conversations.last_customer_message_at TIMESTAMPTZ NULL` (if absent).

## Tests

4 pytest + 2 Jest.

## Smoke

```
1. Open in-session WhatsApp conversation → green banner "Free session — expires in X".
2. Composer accepts regular text + sends.
3. Open out-of-session conversation → yellow banner + composer text disabled.
4. Click [Pick template] → template picker opens (Step 9 surface).
5. Send template → conversation refreshes; banner state remains until contact replies.
6. Contact replies → green banner + composer re-enabled.
7. Non-WhatsApp conversations show no banner.
```

## Risks

- Client-side timer drift — recompute on focus + reuse server timestamp.
- Boundary case at exactly 24h — round down: in-session if < 24h.
- Existing conversations may lack timestamp — backfill or treat as out-of-session.

## Self-check (10 rules)

All `core/conversations/`. ✓. org_id + RLS preserved. ✓. No custom-field changes. ✓. Static UI. ✓ N/A. No registry change. ✓. Existing permission. ✓. pack.yaml untouched. ✓. 8 files / ~300 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 15 — Session window banner
Files: 8
Verify: banner state + composer disable + template CTA out-of-session.
Tests: 4 pytest + 2 Jest.
Phase 5 (conversations features) complete. Next: Step 16 — welcome + out-of-hours auto-reply.
Awaiting "proceed".
```
