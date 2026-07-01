# Step 5 — Frontend Connect card + sync badges

**Goal:** Employee opens `/user/integrations` → sees a Google Calendar
card with a Connect button. After OAuth they land back with "Connected
as ajay@gmail.com". Appointment detail page shows a "Synced to Google
Calendar ✓" chip.
**Status:** Pending
**Depends on:** Steps 2-4 (endpoints + sync backend).

---

## Scope

### Integrations page card

`APP/src/app/features/user/core/settings/integrations/` — add a
`GoogleCalendarCardComponent`.

**Disconnected state:**
```
┌─ Google Calendar ─────────────────────────────────────┐
│ 📅 Google Calendar                                    │
│    Sync your appointments to your Google Calendar     │
│                                    [ Connect ]        │
│    One-way sync · Personal to you                     │
└──────────────────────────────────────────────────────┘
```

**Connected state:**
```
┌─ Google Calendar ─────────────────────────────────────┐
│ 📅 Google Calendar             ✅ Connected           │
│    Connected as ajaygogane224@gmail.com               │
│    Last synced: 2 minutes ago                         │
│                                  [ Disconnect ]       │
│    One-way sync · Personal to you                     │
└──────────────────────────────────────────────────────┘
```

**Error state (revoked / API failure):**
```
┌─ Google Calendar ─────────────────────────────────────┐
│ 📅 Google Calendar             ⚠️ Reconnect needed    │
│    Google reported: token revoked                     │
│                                    [ Reconnect ]      │
└──────────────────────────────────────────────────────┘
```

The card polls `/integrations/google-calendar/status` every 5s WHILE
the OAuth popup is open (so the connected state flashes in the moment
the user grants). Otherwise it fetches once on mount.

### Router landing handler

`/user/integrations?status=connected` → toast "Google Calendar
connected as {email}" + refetch status.
`/user/integrations?status=denied` → toast "Connection cancelled".

### Per-appointment badge

On `/user/appointments/{id}` detail page — add a small chip in the
header row:

- Assignee HAS Calendar connected + appointment has an event_id
  → green chip "Synced ✓" + tooltip "In {email}'s calendar since {ts}"
- Assignee has Calendar connected + no event_id (task pending or
  errored) → amber chip "Sync pending"
- Assignee doesn't have Calendar connected → grey chip
  "{name} hasn't connected Google Calendar"

Chip is display-only — no click action for v1.

### Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/settings/integrations/google-calendar-card.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/settings/integrations/integrations-page.component.html` | edit — mount the card |
| `APP/src/app/features/user/core/settings/integrations/integrations-api.service.ts` | edit — 4 methods (status / authorize / disconnect / (later: reconnect)) |
| `APP/src/app/features/user/core/appointments/appointment-detail.page.{ts,html}` | edit — sync chip in header |
| `APP/src/app/app.config.ts` | edit — register Lucide icons if any new ones |

**~5 files, ~350 lines.**

## Verify

1. Ajay opens `/user/integrations` → Google Calendar card visible with
   "Connect" button
2. Click Connect → new tab opens Google's consent → grant → tab
   closes / redirects back → card now shows "Connected as
   ajaygogane224@gmail.com"
3. Create an appointment for Ajay → open appointment detail → green
   "Synced ✓" chip visible within 5s
4. Reassign the appointment to an employee who hasn't connected → chip
   flips to grey "hasn't connected Google Calendar"
5. Click Disconnect → confirm → card flips back to "Connect" state

## Self-check

Uses existing Tailwind conventions + Lucide icons registered in
`app.config.ts`. No new node modules. Prettier-clean on write.
Angular signals + `@if` narrowing. Stop-report.
