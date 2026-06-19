# Step 7 — Reply / quote previous message + reactions

**Goal:** Standard WhatsApp UX additions — reply-to-quote any previous message in the thread (with quoted snippet rendered above the new bubble) and react to a message with emoji. Both supported in outbound + parsed in inbound.
**Status:** Pending
**Depends on:** Step 6 (composer has builder-modal pattern established).

---

## Scope

In-scope:
- Add `tbl_conversation_messages.reply_to_message_id UUID NULL` FK (self-referencing).
- Send: `context: { message_id: <meta_message_id> }` to Cloud API for quoted replies.
- Send reactions: `POST /messages` with `type: reaction`, body `{ message_id, emoji }`. Empty emoji removes a reaction.
- Inbound webhook: capture `context.id` for replies; `reactions[]` for reaction events.
- Composer: hover/long-press action bar with Reply, React, Copy.
- Reply mode: quoted snippet renders above composer with X-to-clear.
- Reaction picker: 6 emojis + "more" expander.
- Thread renders quoted-block at top of reply bubbles.
- Reactions render as small emoji indicator below the parent message bubble.

Out of scope:
- Typing indicators (outbound) — Cloud API does not support; inbound typing handled passively if Meta sends.
- Delete-for-everyone — Meta requires special API call; defer.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/conversations/models.py` | Add `reply_to_message_id` FK |
| `API/alembic/versions/<ts>_conversation_reply_to.py` | **NEW** migration + index |
| `API/src/app/core/conversations/adapters/whatsapp.py` | Extend send for context + reaction body |
| `API/src/app/core/conversations/adapters/whatsapp.py` (parse_webhook) | Parse reactions + context_id |
| `APP/.../conversations/thread/message-bubble.component.ts` | Hover action bar + quoted-block render + reactions row |
| `APP/.../conversations/thread/reaction-picker.component.ts` | **NEW** |
| `APP/.../conversations/composer/composer.component.ts` | Reply mode UI (quoted snippet + clear) |
| `API/tests/conversations/test_whatsapp_reply_reactions.py` | **NEW** |

**~8 files. ~350 lines.**

## Plan

1. Migration: add FK + index on `(conversation_id, reply_to_message_id)`.
2. Send pipeline: if `reply_to_message_id` present, resolve to Meta message_id (we cache Meta IDs on outbound rows already; check `tbl_conversation_messages.meta_message_id`).
3. Reactions: separate code path; send minimal payload; persist as message of `type: reaction`.
4. Inbound parse: `context.id` → resolve our message ID via `meta_message_id` index; set reply_to.
5. Reaction inbound: append to parent message's `reactions JSONB`. If empty emoji → remove.
6. Frontend: action bar appears on hover (desktop) or long-press (touch). Reply pushes thread state into "replying-to" mode; clear button or Esc exits.
7. Render: quoted-block reuses styling of WhatsApp's snippet (border-left + truncated text).
8. Tests: outbound with context, inbound parse of context_id, reaction add/remove cycle.

## DB changes / migrations

- `tbl_conversation_messages.reply_to_message_id UUID NULL`
- Optional: `tbl_conversation_messages.reactions JSONB DEFAULT '[]'`
- Index `(conversation_id, reply_to_message_id)` partial NOT NULL.

## Tests

6 pytest cases.

## Smoke

```
1. Send a text. Recipient replies. Hover the inbound message → action bar → Reply → composer shows quoted block. Type "Sure" → Send.
2. Recipient sees "Sure" as a quoted reply to their original message.
3. Hover any message → action bar → React → pick 👍. Recipient sees 👍 below message.
4. React with different emoji → replaces 👍.
5. React with same emoji again → removes.
6. Inbound reactions arrive on parent message correctly.
7. Reply to media message works (quoted snippet shows "📷 Photo").
```

## Risks

- Reply-to across pagination: quoted message may not be in viewport. Render the snippet stand-alone (we have body from cache); link "Jump to message" scrolls into view.
- Reactions on group conversations — not applicable here (1:1 only on Cloud API today).
- Meta limits 1 reaction per user per message; UI replaces locally to match.

## Self-check (10 rules)

All `core/conversations/`. ✓ Rules 1-7. ~8 files / ~350 lines. ✓ Rule 8. Stop-report. ✓ Rule 9. No TODOs. ✓ Rule 10.

## Stop & report

```
Step 7 — Reply/quote + reactions
Files: 8
Verify: outbound reply with quoted snippet; inbound parse; reaction add/replace/remove cycle.
Tests: 6 pytest cases.
Phase 2 (send richness) complete. Next: Step 8 — template management backend.
Awaiting "proceed".
```
