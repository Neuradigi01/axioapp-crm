# Step 3.10 — Conversations: frontend

**Goal:** Unified inbox matching the screenshot. Left: conversation list with channel badges + filters. Right: chat thread. AI Handled / Needs Human badge. "Type a reply or let AI handle it" input. WS-driven real-time updates.
**Phase:** 3
**Depends on:** 3.8, 3.9, 2.16
**Status:** Pending

## Scope
**In-scope:**
- `app/src/app/features/user/core/conversations/`:
  - `conversations-api.service.ts`
  - `conversations.page.ts/.html` — split layout, signal-based selection.
  - `conversation-list.component.ts/.html`
  - `chat-thread.component.ts/.html` — message bubbles, attachments preview, typing indicator placeholder.
  - `compose-bar.component.ts/.html` — input, send, "Let AI handle it" toggle (writes to `ai_handling`).
- WS subscription on conversations stream: a server-sent topic via the existing `/notifications/stream` endpoint OR a new dedicated WS — DEFAULT decision: reuse notifications WS with `type='conversation_update'` payloads.
- Tailwind only.

## Files to touch
- `app/src/app/features/user/core/conversations/*` (created)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. List page with filters: channel, status, assigned-to, search.
2. Chat thread auto-scrolls to bottom; loads more on scroll up.
3. Compose bar: send via `POST /conversations/{id}/messages`; optimistic append.
4. WS hook: on `conversation_update` payload, refresh list ordering + thread if open.
5. Channel badges: WhatsApp green, Instagram gradient, Facebook blue, etc.

## Verification checklist
**Frontend:**
- visit `/conversations` → list of conversations.
- click one → thread loads.
- send text → appears in thread; backend records outbound message.
- inbound (via webhook simulation) → list updates in real time, unread badge increments.

## Self-check (10 rules)
- [ ] No hardcoded channel logic in page (all driven by `channel` field).
- [ ] Tailwind only.

## Stop & report
Await "proceed" before Step 3.11.
