# AI Assistants — omnichannel + human takeover

Extend the existing `core/ai_assistants/` module (public widget only today) so an org's AI Assistant can auto-answer inbound messages on **any** connected channel — WhatsApp, Email, Website widget — and any employee can jump into the same conversation thread at any time.

## Why this track exists

Today the AI Assistant is wired to exactly one entry point: the public embed widget (`/api/v1/public/ai-assistants/message`). Meanwhile:

- **WhatsApp** has partial AI wiring via `integrations/whatsapp/ai_handler.py` — but it fires only when `tbl_conversations.ai_handling` is manually toggled per-conversation. No default-on, no channel binding on the assistant side.
- **Email** has zero AI wiring — inbound emails land in the inbox as human-only conversations.
- **Human takeover** exists in the WhatsApp path (auto-escalation on low confidence, keyword handover) but not for widget or email. There's no "Take Over" button anywhere in the UI.

Operators expect the reverse of today: AI answers **by default** on every channel the assistant is bound to; a human clicks one button to take over any conversation, first-come-first-serve.

## What this track ships

- **Extend `core/ai_assistants/`** — `tbl_ai_assistants` grows `bound_channels JSONB DEFAULT '[]'`. Editor UI adds channel checkboxes. Save through existing PATCH.
- **Extend `core/conversations/`** — `tbl_conversations` grows `ai_paused BOOL DEFAULT false` + `ai_paused_by_user_id UUID NULL` + `ai_paused_at TIMESTAMPTZ NULL`. New endpoints `POST /conversations/{id}/pause-ai` and `POST /conversations/{id}/resume-ai`. Compare-and-set on the flag for first-come-first-serve race handling. WebSocket event `conversation.ai_paused` broadcasts to all connected employees.
- **New `core/conversations/ai_dispatch.py`** — single channel-agnostic entry point. Called by every channel's inbound webhook. Looks up the org's assistant bound to the inbound's channel; if `ai_paused=false` runs the shared `ai_assistants/runtime.py`; sends the reply back through the channel's existing outbound adapter.
- **Refactor `core/ai_assistants/runtime.py`** — decouple from the widget-only `is_public` / `embed_key_id` context so WhatsApp + Email can call the same brain. Add a `ChannelContext` abstraction that owns "how do I send a reply back on this channel."
- **Extend WhatsApp inbound** — `receive_webhook()` now calls `ai_dispatch.route()`. Existing `ai_handler.py` becomes a thin shim (or is deleted — Step 5 decides after diff-check).
- **Extend Email inbound** — new hook in the Gmail/Microsoft sync path calls `ai_dispatch.route()` with an email-specific `ChannelContext`. Guardrails filter role accounts, bulk mail, bounces, empty bodies.
- **Frontend surfaces** — channel-binding checkboxes in the Assistant editor (Step 2); "🤖 AI active" pill + "Take Over" / "Return to AI" buttons in the conversation detail (Step 4); AI status column in the conversation list (Step 4).

## What this track does NOT include (v1)

- **Instagram / Messenger / SMS channels** — deferred; the `bound_channels` shape supports them without a migration, but the inbound adapters are separate work.
- **Multi-assistant routing per org** — one assistant per (org, channel) in v1. If an org has two assistants both bound to WhatsApp, the save endpoint rejects. Multi-assistant routing (e.g., by keyword, by hour of day, by ML classifier) is future work.
- **AI Draft Mode for email** — v1 auto-sends AI email replies (with guardrails). "AI drafts, human sends" mode is a separate future feature with different UX.
- **Analytics for AI takeover rate** — Step 5 stores the events (`ai_paused_at`, who paused) but no dashboard is built. Analytics tab in a future track.
- **Auto-resume after N minutes of silence** — v1 requires an explicit "Return to AI" click. Auto-resume is a follow-up if operators ask for it.
- **Confidence-based auto-pause** — v1 relies on explicit keyword handovers ("talk to a human", "stop", "human please"). LLM-self-scored confidence gating is future work.
- **Per-conversation assistant override** — the assistant used is always the org's bound assistant for that channel. No "route this thread to a specific assistant" v1.

## Multi-tenancy + secret handling

Every new row is `org_id`-scoped and RLS-covered from the migration that creates it (no changes to existing tenant model). Bearer-key auth for the widget path stays exactly as-is; WhatsApp + Email inbound authentication is unchanged (webhook signature verification remains in each channel's existing handler). The `pause-ai` / `resume-ai` endpoints are JWT-gated (`conversations.reply` permission).

## Locked design choices (won't relitigate during implementation)

### 1. `bound_channels` is a JSONB array on the assistant

`tbl_ai_assistants.bound_channels JSONB DEFAULT '[]'::jsonb` — string array of channel keys: `["ai_widget", "whatsapp", "email"]`. Not boolean columns per channel — JSONB extends to Instagram/Messenger/SMS without a migration. GIN index `USING gin (bound_channels)` for the dispatch query `WHERE bound_channels ? :channel`. **Uniqueness constraint** enforced at the service layer (not DB — Postgres can't cleanly constrain "unique element in a JSONB array within org"): on save, reject if another active assistant in the same org already binds this channel.

**Benchmark:** Intercom uses per-inbox routing (many-to-many "which bot handles which inbox"). Wati and Interakt use one-bot-per-account. HubSpot uses one bot per channel. **We match HubSpot** — simplest mental model for the operator, defers routing complexity. *Unsourced (interim benchmark; brief absent).*

### 2. Human takeover = boolean flag with compare-and-set

`tbl_conversations.ai_paused BOOL DEFAULT false`. `POST /pause-ai` runs `UPDATE ... SET ai_paused=true, ai_paused_by_user_id=$1, ai_paused_at=now() WHERE id=$2 AND org_id=$3 AND ai_paused=false RETURNING id`. If no row returned → 409 with reason `already_taken_over` + the current holder's name (so the loser's UI can show "Alice just took this over"). Not a lock — a single-column CAS. No Redis, no locks, no pg advisory.

**Benchmark:** Intercom Fin uses a "handoff to team" model with explicit routing. Zendesk Answer Bot uses "resolve or escalate" with team assignment. **We match neither exactly — closer to Front's shared inbox.** First employee to click wins the conversation; others see it's taken. Simple, matches how customer-support teams already work. *Unsourced.*

### 3. Auto-pause on human message, plus manual "Take Over"

If a human types the first outbound message on a conversation where `ai_paused=false`, the outbound handler transparently sets `ai_paused=true, ai_paused_by=me` before the send. This handles the case where an employee just replies without noticing the AI pill — they get takeover implicitly. The "Take Over" button is for **pre-emptive** pause (before typing).

**Benchmark:** Intercom Fin does auto-pause-on-human-message. Wati does not (requires explicit toggle). **We match Intercom** — less UX friction. *Unsourced.*

### 4. Handover keywords work on every channel

Existing `integrations/whatsapp/ai_handler.py` has keyword handover ("talk to human", "human please", etc.). Step 5 moves this list into `core/ai_assistants/handover.py` and calls it from `ai_dispatch.route()` before the LLM call — so keyword handover works on Widget + WhatsApp + Email uniformly. Auto-pauses + optionally notifies the org's on-duty employees.

### 5. Email guardrails: reply-worthiness filter

Before dispatching an inbound email to the AI, `ai_dispatch.route()` runs a filter that rejects:

- Sender local-part in `{no-reply, noreply, notifications, postmaster, bounces, mailer-daemon, do-not-reply, donotreply}` (case-insensitive)
- Presence of `Auto-Submitted:` header (RFC 3834 — set by every legitimate auto-responder)
- Presence of `List-Unsubscribe:` header (RFC 2369 — set by every legitimate list mailer)
- `Precedence: bulk` / `Precedence: list` / `Precedence: junk` header
- Empty body (only attachments, or only quoted history under 20 chars)
- Bounce indicators (`X-Failed-Recipients`, subject starts with `Delivery Status Notification` / `Undelivered Mail`)

Rejected emails still land in the conversations inbox — they're just not answered by the AI. **This filter is a hard gate; there is no operator override in v1.**

### 6. Email threading — reuse existing outbound module

The email outbound module (`core/email/` + `core/email_senders/`) already handles `In-Reply-To`, `References`, `Re:` subject prefix, and quoted-history in the body. The AI dispatch calls it exactly like a human employee does. No new email plumbing.

### 7. Same runtime, per-channel context

`core/ai_assistants/runtime.py`'s `ChatRuntime` grows a `ChannelContext` param that owns three things: (a) how to load conversation history, (b) how to send the reply back, (c) whether this is a "public" call (widget, hides `instructions` from responses) or "authenticated org" call (WhatsApp/Email are always org-authenticated). The three concrete `ChannelContext` implementations — `WidgetContext`, `WhatsAppContext`, `EmailContext` — live in `core/conversations/channel_contexts/`. This keeps `runtime.py` channel-agnostic.

### 8. Auto-enable on new inbound conversations

When a new conversation is created (via WhatsApp webhook or new email thread), the conversation's `ai_paused` defaults to **false**. The dispatch check then keys off "is a bound assistant configured for this channel?" — if yes, AI runs; if no, nothing happens (human handles normally). No per-conversation opt-in required from the operator.

**Benchmark:** Intercom Fin defaults to on-per-channel (matches ours). Wati defaults to off (requires per-thread toggle). We deliberately match Intercom — the operator's setup work happens once (bind assistant to channel) instead of per-conversation. *Unsourced.*

### 9. WebSocket-driven inbox refresh

When `ai_paused` flips (either direction) or a new AI turn streams into a conversation, the conversations WebSocket channel (already exists — used by inbox live-refresh today) broadcasts a `conversation.updated` event with the delta. Two employees looking at the same inbox see each other's takeovers in near-real-time; the "Take Over" button on Alice's screen disappears within 1s of Bob clicking it.

### 10. No new permission keys

`conversations.reply` (existing) gates `pause-ai` / `resume-ai`. `ai_assistants.manage` (existing) gates channel-binding edits. No new perms invented — the RBAC surface stays flat.

## Cases

- **Two employees click "Take Over" simultaneously** → single-column CAS ensures one 200 + one 409. Loser gets toast: *"Alice just took this over."* WebSocket refreshes their inbox.
- **AI reply is mid-stream when human clicks "Take Over"** → in-flight LLM stream continues (interrupt-safe abandonment is expensive); the stream's final reply is appended AND a system message `"— Alice took over ─"` is inserted. Next inbound gets no AI.
- **Assistant is archived while conversations are still AI-active** → `ai_dispatch.route()` re-reads the assistant on every inbound; archived → `assistant not found` → silent skip (no AI reply; conversation waits for human). No orphan runaway.
- **Assistant is unbound from a channel** while conversations still `ai_paused=false` → same as archived: dispatch check fails, no AI, human handles.
- **Two assistants in same org try to bind WhatsApp** → save endpoint returns 409 `channel_already_bound` naming the other assistant.
- **A human types a reply on a conversation with `ai_paused=false`** → outbound handler auto-flips `ai_paused=true` before send (silent, no UI ceremony). Audit row captures it.
- **Email inbound from `no-reply@amazon.com`** → guardrail filter rejects; email lands in inbox as unread but no AI reply.
- **Email inbound with `List-Unsubscribe:` header** → guardrail rejects.
- **Widget user sends "talk to a human"** → handover keyword check fires before LLM call; conversation `ai_paused=true`, notification to on-duty employees, AI silently steps back.
- **WhatsApp customer messages an org with NO assistant bound to WhatsApp** → dispatch check fails silently; conversation waits for human like today.
- **Backend restart mid-conversation** → session cache in `runtime.py` is repopulated on next inbound; `ai_paused` is persisted (DB, not memory) so takeover state survives.

## Tests

- **Step 1** — migration up + down; `bound_channels` defaults to `[]`; PATCH updates array; service-layer uniqueness rejection when two assistants bind the same channel.
- **Step 2** — checkbox state syncs to `bound_channels` array; Save button dirties on toggle; assistant editor shows current binding on load; toast on save-conflict when another assistant already owns the channel.
- **Step 3** — `POST /pause-ai` on unpaused conversation returns 200 + sets flag; second concurrent call returns 409 `already_taken_over` naming the winner; `resume-ai` requires the caller to be the current holder OR an admin; both emit WebSocket events.
- **Step 4** — "Take Over" button visible only when `ai_paused=false` + user has `conversations.reply`; button disappears via WebSocket when another user takes over; "Return to AI" reciprocal button; AI status pill in list column reflects live state.
- **Step 5** — WhatsApp inbound with bound assistant + `ai_paused=false` triggers AI reply; with `ai_paused=true` no AI reply fires; assistant not bound to WhatsApp → no AI; handover keyword auto-pauses + notifies; email inbound routes through same dispatch; `WidgetContext` legacy path (`/public/ai-assistants/message`) still works unchanged.
- **Step 6** — email from `no-reply@` skipped; email with `List-Unsubscribe` skipped; bounce email skipped; empty-body email skipped; normal email replies with correct `In-Reply-To` header + quoted history; `Re:` prefix applied without duplicating on already-`Re:`-prefixed subjects.

## Order (dependencies)

```
Step 1 (backend model + migration)
   ↓
Step 2 (channel binding UI) ── independent of ─→ Step 3 (pause-ai endpoints)
                                                      ↓
                                                 Step 4 (takeover UI)
                                                      ↓
Step 5 (unified inbound dispatch — needs bound_channels from Step 1 + ai_paused from Step 3)
   ↓
Step 6 (email guardrails — extends Step 5's email path)
```

Steps 2 + 3 are parallelizable if two people work — but for solo execution, in-order is fine.

## Steps

| # | File | Est. time | Status | Depends on |
|---|---|---|---|---|
| 1 | [step-1-bound-channels-model.md](step-1-bound-channels-model.md) | ~45 min | ✅ COMPLETED | — |
| 2 | [step-2-channel-binding-ui.md](step-2-channel-binding-ui.md) | ~45 min | ✅ COMPLETED | Step 1 |
| 3 | [step-3-ai-paused-endpoints.md](step-3-ai-paused-endpoints.md) | ~1 hr | ✅ COMPLETED | — |
| 4 | [step-4-takeover-ui.md](step-4-takeover-ui.md) | ~1 hr | ✅ COMPLETED | Step 3 |
| 5 | [step-5-inbound-dispatch.md](step-5-inbound-dispatch.md) | ~2 hr | ✅ COMPLETED (thin) | Steps 1 + 3 |
| 6 | [step-6-email-guardrails.md](step-6-email-guardrails.md) | ~1 hr | ✅ COMPLETED | Step 5 |

**Total: ~6.5 hr focused work.** All backend + frontend + migration + tests included.
