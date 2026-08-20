# Step 3 — `ai_paused` column + `pause-ai` / `resume-ai` endpoints

**Goal:** Extend `tbl_conversations` with a boolean AI-pause flag + who-paused + when. Add two POST endpoints — `/pause-ai` (first-come-first-serve via compare-and-set) and `/resume-ai` (holder-or-admin only). Emit `conversation.updated` WebSocket events on both flips so all connected inbox tabs refresh live.
**Status:** Pending
**Depends on:** — (parallelizable with Step 2 after Step 1).

---

## Scope

In-scope:

- Migration `<ts>_conversations_ai_paused.py`:
  - ALTER `tbl_conversations` ADD COLUMN `ai_paused BOOL NOT NULL DEFAULT false`.
  - ADD COLUMN `ai_paused_by_user_id UUID NULL` (no FK — legacy user PK convention).
  - ADD COLUMN `ai_paused_at TIMESTAMPTZ NULL`.
  - Partial index `ix_conversations_ai_paused ON tbl_conversations (org_id, ai_paused) WHERE ai_paused = false` (dispatch's hot path).
- Model — `Conversation.ai_paused`, `ai_paused_by_user_id`, `ai_paused_at`.
- Schema — `ConversationRead` gains all three fields (nullable ones as `| None`).
- New router endpoints in `conversations/router.py`:
  - `POST /conversations/{id}/pause-ai` — auth: JWT + `conversations.reply` permission.
  - `POST /conversations/{id}/resume-ai` — same auth; additionally requires caller is the current holder OR has `conversations.manage` (Admin+).
- Service — `pause_ai(db, org_id, conv_id, actor_user_id)` runs the compare-and-set:
  ```sql
  UPDATE tbl_conversations
  SET ai_paused = true,
      ai_paused_by_user_id = :actor,
      ai_paused_at = now()
  WHERE id = :conv_id
    AND org_id = :org_id
    AND ai_paused = false
  RETURNING id;
  ```
  If no row returned → fetch the current holder and raise `HTTPException(409, {"reason": "already_taken_over", "holder_user_id": <uuid>, "holder_name": <display>, "paused_at": <ts>})`.
- Symmetric `resume_ai(...)` — clears the three fields with a CAS on `ai_paused = true`.
- Both paths call `_broadcast_conversation_updated(conv_id, org_id)` — existing WebSocket helper (or new tiny helper if the conversations module doesn't have one; Step 3 Plan phase checks). Payload: full `ConversationRead`.
- System message insertion — after successful pause: insert a system-authored message into `tbl_messages` with body `"— {holder_name} took over from AI —"`. After resume: `"— {holder_name} returned this conversation to AI —"`. Message rendered inline in the conversation detail with a distinct system-message style.

Out of scope:

- UI (Step 4).
- Auto-pause on human outbound (Step 5 — needs the dispatch refactor).
- Handover-keyword-triggered pause (Step 5 — same reason).
- Admin override force-unassign (v1: any `conversations.manage` holder can resume; no forced re-assign UI).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_conversations_ai_paused.py` | **NEW** |
| `API/src/app/core/conversations/models.py` | **EDIT** — three columns |
| `API/src/app/core/conversations/schemas.py` | **EDIT** — extend `ConversationRead` |
| `API/src/app/core/conversations/router.py` | **EDIT** — two new endpoints |
| `API/src/app/core/conversations/service.py` | **EDIT** — `pause_ai` + `resume_ai` |
| `API/src/app/core/conversations/data_access.py` | **EDIT** — CAS query + holder lookup |
| `API/tests/conversations/test_ai_pause_resume.py` | **NEW** |

**~7 files, ~350 lines.**

## Plan

1. Migration inspects existing columns first — refuses if any of the three names collide.
2. Partial index: `WHERE ai_paused = false` — the vast majority of conversations aren't paused; the dispatch check reads only unpaused rows so a partial index is small + fast.
3. CAS is a single-statement `UPDATE ... RETURNING id` — no lock, no serializable isolation needed. Postgres row lock covers the CAS window.
4. Holder-name lookup — after 409, service fires a second query on `tbl_user_login` for `first_name || ' ' || last_name`. One extra hop, acceptable on the loser's path.
5. Resume: additional server-side check. Read `ai_paused_by_user_id`; if caller isn't that user AND caller lacks `conversations.manage`, return 403 `not_holder`.
6. WebSocket event: the existing conversations WS registry (used for new-message push) already publishes per-org channels. Reuse — payload includes the fresh `ConversationRead` so client can render the pill + button change without a re-fetch.
7. System message: use existing message insertion path (`data_access.insert_message`) with `sender_type='system'`, no `sender_user_id`, body auto-formatted with the holder's display name. Consistent with existing "conversation reassigned" system messages if any (check on Plan).

## DB changes / migrations

```sql
ALTER TABLE tbl_conversations
  ADD COLUMN ai_paused BOOL NOT NULL DEFAULT false,
  ADD COLUMN ai_paused_by_user_id UUID NULL,
  ADD COLUMN ai_paused_at TIMESTAMPTZ NULL;

CREATE INDEX ix_conversations_ai_paused
  ON tbl_conversations (org_id, ai_paused)
  WHERE ai_paused = false;
```

Down: drop index, drop three columns.

## Tests (`test_ai_pause_resume.py`)

- **Migration up/down clean.**
- **Pause on unpaused** — 200, `ai_paused=true`, `ai_paused_by_user_id` = caller, `ai_paused_at` recent. System message inserted.
- **Concurrent pause race** — two parallel `POST /pause-ai` calls; one 200, one 409 with holder fields populated. Only one system message inserted.
- **Pause on already-paused** — 409 with same body as race case.
- **Resume by holder** — 200, all three columns cleared. System message inserted.
- **Resume by non-holder without admin** — 403 `not_holder`.
- **Resume by non-holder WITH `conversations.manage`** — 200.
- **Resume on unpaused** — 409 `not_paused`.
- **WebSocket event** — pause emits `conversation.updated` with `ai_paused=true`; resume emits with `ai_paused=false`. (Fake WS registry in test.)
- **Cross-org** — org A pauses their conv, org B's identical pause call on THEIR own conv doesn't affect A. RLS.
- **Missing conversation** — 404, no side effects.

## Self-check checklist

- [ ] Rule 2 — new columns are on existing `tbl_conversations` (already RLS-scoped).
- [ ] Rule 8 — 7 files, ~350 lines. Under ceiling.
- [ ] Router → Service → DAL — endpoints thin; CAS in DAL; service does the holder-lookup + permission gating + system-message insertion.
- [ ] Transaction discipline — service owns the transaction (single UPDATE + optional message INSERT); DAL doesn't commit.
- [ ] Rule 3 (custom-field layered model) — N/A.
- [ ] WebSocket reuse (no new WS channel invented).

## Stop-and-report template

> Files changed: `<list>`
> What you can verify: `curl -X POST /api/v1/conversations/{id}/pause-ai` returns 200 with the conversation showing `ai_paused=true`. A second concurrent call returns 409 naming the holder. Resume works. WebSocket event delivered to an inbox tab.
> Tests added: `test_ai_pause_resume.py` (11 assertions).
> Self-check: pass · pass · pass · pass · pass · pass.
> Awaiting your 'proceed'.
