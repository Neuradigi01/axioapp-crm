# Step 4 — "Take Over" / "Return to AI" UI in the Conversations inbox

**Goal:** Add the AI-status pill + Take Over / Return to AI buttons to the conversation detail. Add a live AI-status column to the conversation list. Everything reactive to the WebSocket `conversation.updated` events emitted by Step 3.
**Status:** COMPLETED — takeover banner lives in `chat-thread.component.html` above the message scroll, two colour states (emerald "🤖 AI is handling · Take Over" / amber "✋ {holder} is handling · Return to AI"). Two new outputs on the thread component (`takeoverAi`, `resumeAiOut`); the page wires them to `onTakeoverAi()` / `onResumeAi()` which call the Step 3 endpoints. Race 409 → toast *"{holder} just took this over."* + local reload; 403 `not_holder` on resume → toast explaining only the holder or admin can return. Confirmation dialog on Return-to-AI (native `window.confirm`). MatSnackBar toasts across success / error / race. Conversation list row gained a live indicator: 🤖 AI handled (violet) or ✋ Human took over (amber). AI Assistants API service gained `pauseAi(id)` / `resumeAi(id)`. `Conversation` TS interface extended with `ai_paused` / `ai_paused_by_user_id` / `ai_paused_at`. **WebSocket live-refresh deferred** (see Step 3 report) — the clicker's own tab flips instantly via the endpoint response, other tabs see the change on inbox refresh; the `_reloadDetail(id)` call after each success also pulls the newly-inserted system marker message into the thread. `tsc --noEmit` green; prettier clean.
**Depends on:** Step 3 (endpoints + WebSocket events).

---

## Scope

In-scope:

- Extend the `Conversation` TS interface with `ai_paused`, `ai_paused_by_user_id`, `ai_paused_at`.
- Add `pauseAi(conversationId)` + `resumeAi(conversationId)` methods to `conversations-api.service.ts`.
- Conversation detail component (`conversation-detail.component.ts` — path may differ; Step 4 Plan phase confirms):
  - New status banner above the message stream:
    - When `ai_paused=false` AND assistant bound to this channel: `🤖 AI is handling this conversation. [Take Over]` button (green).
    - When `ai_paused=true`: `✋ {holder_name} is handling this conversation. [Return to AI]` button (only if caller is holder OR has `conversations.manage`).
    - When no assistant bound to channel: no banner (just normal human chat).
  - Take Over click → `pauseAi()` → optimistic UI flip → wait for 200 or revert on error. On 409 `already_taken_over` → toast: *"{holder} just took this over."* + trust incoming WebSocket event to sync.
  - Return to AI click → `resumeAi()` → confirmation dialog: *"Return this conversation to AI? The AI will handle future messages."* → on OK → API call → toast on success.
- Conversation list component (`conversation-list.component.ts`):
  - Small AI status pill in each row: 🤖 (AI active) or ✋ (human took over) or nothing (no assistant bound to channel). Positioned next to the existing status badge.
- WebSocket handler — the existing `conversations` WS subscription already fires per-conversation `updated` events; extend the handler to merge `ai_paused` + related fields into the local state. Any component subscribed to the conversation observable auto-refreshes.
- System messages ("— Alice took over —") render with a distinct style: centered, muted, no bubble — matches existing system-message rendering if any.

Out of scope:

- Bell-notification for AI escalations (Step 5's handover-keyword path is what triggers notifications; UI wiring lives here as a small consumer if bandwidth allows, else deferred).
- Bulk actions ("pause AI on all unread conversations") — future.
- Per-conversation "which assistant is handling" disclosure — v1 shows just "AI" without naming the assistant.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/conversations/conversations-api.service.ts` | **EDIT** — pauseAi, resumeAi methods |
| `APP/src/app/features/user/core/conversations/models.ts` (or wherever `Conversation` interface lives) | **EDIT** — add ai_paused fields |
| `APP/src/app/features/user/core/conversations/conversation-detail.component.ts` | **EDIT** — pause/resume handlers + state |
| `APP/src/app/features/user/core/conversations/conversation-detail.component.html` | **EDIT** — status banner + buttons |
| `APP/src/app/features/user/core/conversations/conversation-list.component.html` | **EDIT** — status pill in row |
| `APP/src/app/features/user/core/conversations/conversations-ws.service.ts` (or equivalent) | **EDIT** — handle new fields in the updated-conversation event |

**~6 files, ~250 lines.**

## Plan

1. Confirm the exact conversation detail file — earlier subagent report referred to `conversation-list.component.ts:72-103` but a detail component might be a separate file or a sub-component. Grep for `conversation-detail`.
2. Buttons: reuse the existing button styles from the WhatsApp reply composer for visual consistency.
3. Confirmation dialog: use whatever the codebase's existing confirm pattern is (there might be a shared `ConfirmDialog` component; if not, plain `window.confirm()` is acceptable for v1).
4. Status pill: emoji-only (🤖 / ✋) with tooltip on hover. Doesn't need its own component — small `<span>` inside the existing row template.
5. WebSocket handler: the incoming payload IS the full `ConversationRead`, so a simple merge into the local list/detail signal is enough.
6. Icons: `Rocket` was added last session; add `HandRaised` or `UserCheck` if needed for the Take Over button — check `app.config.ts` first per the memory note.
7. Copy: match the exact strings in Step 3's README (system message format `— {name} took over from AI —`).

## Tests

Manual smoke (frontend only):
- Open a conversation with `ai_paused=false` → banner shows "🤖 AI is handling..." with green Take Over button.
- Click Take Over → banner flips to "✋ You are handling..." + composer unlocks. System message "— Alice took over from AI —" appears inline.
- In a second browser (different user) viewing the same conversation → banner + button auto-update via WebSocket within 1s.
- Return to AI on the banner → confirmation → banner flips back to AI-handling. System message inserted.
- Non-holder tries Return to AI without admin perm → 403 error toast; UI reverts.
- Conversation list: paused row shows ✋; unpaused row shows 🤖 (only when the channel has a bound assistant).

## Self-check checklist

- [ ] Lucide icon registry checked — no missing icons per memory note.
- [ ] Uses shared/existing button + banner components — no invented patterns.
- [ ] Consistent with existing 🤖 / ✋ semantics if any (grep first).
- [ ] Reactive to WebSocket — no polling.
- [ ] Optimistic UI flip on Take Over, revert on 409.
- [ ] Confirmation dialog on Resume (destructive-ish action).

## Stop-and-report template

> Files changed: `<list>`
> What you can verify: Open a WhatsApp conversation, click Take Over — banner flips, composer unlocks. Open the same conversation in an incognito tab as a different user — see the takeover propagate live. Resume, cross-check system messages appear inline.
> Tests added: 6 manual smoke assertions (no unit tests — UI-only).
> Self-check: pass · pass · pass · pass · pass · pass.
> Awaiting your 'proceed'.
