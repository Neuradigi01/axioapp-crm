# Step 2.16 — Notifications: frontend

**Goal:** Bell icon in header showing unread count + dropdown. Real-time updates via WebSocket. Toast for new notifications.
**Phase:** 2
**Depends on:** 2.15, 1.10
**Status:** COMPLETED

## Scope
**In-scope:**
- `app/src/app/features/user/core/notifications/`:
  - `notifications-api.service.ts` — REST + WS connection management.
  - `notifications-popover.component.ts/.html` — list with unread highlight, mark all read button.
  - `toast-host.component.ts/.html` — bottom-right toast queue, auto-dismiss.
- Header bell icon shows unread count signal.
- WS auto-reconnect with exponential backoff.
- Tailwind only.

**Out of scope:**
- Push notifications (web push) — later.
- Per-type preferences UI — Settings tab in Phase 3.

## Files to touch
- `app/src/app/features/user/core/notifications/*` (created)
- `app/src/app/features/user/core/layout/header.component.ts/.html` (modified — bell + popover + count)
- `app/src/app/app.config.ts` (modified — provide ToastHost)

## Plan
1. API service connects WS on app start; auto-reconnect.
2. Maintains `unreadCount` signal updated from REST initial load + WS messages.
3. Popover loads recent 20 on open.
4. New WS message → push toast + increment count.
5. Click notification → navigate to `payload.deeplink` if present.

## Verification checklist
**Frontend:**
- log in → WS connects (DevTools Network → Frames).
- trigger a notification (via dev endpoint) → toast appears + bell badge increments.
- click bell → popover lists it.
- click item → routes; mark-read called.

## Self-check (10 rules)
- [ ] No imports from `packs/`.
- [ ] Real-time without polling.

## Stop & report
This concludes **Phase 2**. Await "proceed" before Step 3.1.
