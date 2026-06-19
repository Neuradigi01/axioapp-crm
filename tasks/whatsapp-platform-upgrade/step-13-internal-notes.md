# Step 13 — Internal notes on conversations

**Goal:** Add internal-only notes (with @mentions) on conversations. Notes never send to the customer; appear in the thread with yellow styling + mention notifications go to mentioned staff.
**Status:** Pending
**Depends on:** Phase 1 closed.

---

## Scope

In-scope:
- Extend `tbl_conversation_messages` with `is_internal BOOL DEFAULT FALSE` + `mentioned_user_ids UUID[]`.
- New endpoint `POST /api/v1/conversations/{id}/notes` — body: `text`, `mentions: [user_id]`.
- Notes are NOT sent to WhatsApp / SMS / Email.
- Mention notifications: mentioned users get an in-app notification (reuses existing notifications module).
- Composer tab toggle "Reply / Note" — yellow background in note mode.
- `@` triggers mention dropdown of org staff.
- Notes render in thread with yellow border + "Internal note" label + author + timestamp.
- Notes are excluded from any export / customer-facing surface (re-tested explicitly).

Out of scope:
- Note editing / deletion — defer to a smaller follow-up step if requested.
- Per-note reactions — overkill for v1.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/conversations/models.py` | Add columns |
| `API/alembic/versions/<ts>_conversation_internal_notes.py` | **NEW** migration |
| `API/src/app/core/conversations/router.py` | New `/notes` endpoint |
| `API/src/app/core/conversations/notes_service.py` | **NEW** with mention-notification dispatch |
| `APP/.../conversations/thread/composer.component.ts` | Toggle + @-mention dropdown integration |
| `APP/.../conversations/thread/internal-note.component.ts` | **NEW** bubble |
| `APP/.../conversations/conversations.service.ts` | Add `postNote()` |
| `API/tests/conversations/test_internal_notes.py` | **NEW** |

**~8 files. ~350 lines.**

## Plan

1. Migration: 2 columns nullable, default false / empty array.
2. Service emits notifications via existing notification dispatcher for each mention.
3. Frontend composer toggle changes mode signal; submit dispatches different action.
4. `@` triggers existing mention picker if available; else build a small dropdown.
5. Bubble component renders distinct yellow style + non-customer-visible label.
6. Tests cover: note posted with mentions → notifications dispatched, note not pushed to channel adapter, export excludes notes.

## DB changes / migrations

`is_internal BOOL DEFAULT FALSE`, `mentioned_user_ids UUID[] DEFAULT '{}'`.

## Tests

5 pytest cases + 2 Jest specs.

## Smoke

```
1. Open conversation. Composer → toggle "Note". Type "@Ravi pls call this customer back". Submit.
2. Bubble appears with yellow style. @Ravi gets notification.
3. Reply mode still works.
4. Export the conversation (Step 23 export) → note NOT in transcript.
5. Customer never receives the note.
```

## Risks

- Notification spam if user @-mentions a group — accept; cap at 5 mentions per note via validation.
- Notes count toward "message count" stats — exclude in analytics queries.

## Self-check (10 rules)

All `core/conversations/`. ✓. org_id + RLS via existing table. ✓. No custom-field changes. ✓. Composer is static. ✓ N/A. No registry change. ✓. Existing `conversations.write` permission. ✓. pack.yaml untouched. ✓. 8 files / ~350 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 13 — Internal notes
Files: 8
Verify: note posts internally; mentions notify; export excludes; customer never sees.
Tests: 5 pytest + 2 Jest.
Next: Step 14 — tags & labels.
Awaiting "proceed".
```
