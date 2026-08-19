# Step 16 — Inbox integration + analytics + auto-lead capture

**Goal:** Surface AI-assistant conversations inside the existing inbox (`channel='ai_widget'`) so operators can read them, add notes, and take over conversations from the human-handoff surface. Ship a small per-assistant analytics panel (messages, cost, top questions grouped by `LOWER(TRIM(msg))`). Auto-detect emails in user messages and create/link a lead, or prompt for email at a configurable turn N.
**Status:** COMPLETED
**Depends on:** Step 9 (runtime writes to `tbl_conversations`), Step 5 (`tbl_ai_assistant_message_meta`), existing `core/leads/` for lead ingestion.

---

## Scope

In-scope:

- **Inbox integration** — the existing conversations page (`APP/src/app/features/user/core/conversations/`) already lists by `channel`. Verify and, if needed, extend:
  - Channel filter includes `ai_widget` (add to filter dropdown).
  - Conversation row renders assistant name + session token snippet in the "from" position (rather than a contact name, since end-users are anonymous by default).
  - Message thread reads AI-specific metadata from `tbl_ai_assistant_message_meta` (badge showing model + token cost per assistant reply).
  - Notes panel: operators can add internal notes on AI conversations (reuses existing notes surface).
  - Human takeover: existing takeover UI works; when takeover starts, subsequent messages are sent from the operator (existing `core/conversations/` handles).
  - "Assistant removed" indicator: if `message_meta.assistant_id IS NULL` (assistant deleted), show a small badge on the conversation.
- **Analytics panel** — new route `/user/ai-assistants/:id/analytics`:
  - **Message count** (last 30 days) via `SELECT COUNT(*) FROM tbl_ai_assistant_message_meta WHERE assistant_id=:a AND created_at > now() - '30d'`.
  - **Total cost** (last 30 days) via `SUM(cost_usd)`.
  - **Top questions** — SELECT LOWER(TRIM(content)) as norm, COUNT(*) FROM tbl_messages m JOIN tbl_conversations c ON m.conversation_id=c.id WHERE c.channel='ai_widget' AND c.metadata->>'assistant_id'=:a AND m.direction='inbound' GROUP BY norm ORDER BY COUNT(*) DESC LIMIT 20 — over last 30 days.
  - Simple UI: 2 KPI cards + 1 list of top 20 questions with counts.
- **Auto-lead capture** — extend runtime:
  - Assistant config gets three new fields (added via a small migration ALTER `tbl_ai_assistants`): `lead_capture_mode ENUM('off', 'detect_email', 'ask_at_turn')` default `off`, `lead_capture_turn_n int default 3`, `lead_capture_message text nullable` (the prompt shown at turn N).
  - `detect_email`: after each user message, regex `[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}` — if match, upsert a lead via `core/leads/service.create_or_get_lead(org_id, email=<found>, source='ai_assistant', source_id=assistant.id)`. Attach the conversation to the lead (update `tbl_conversations.contact_id`).
  - `ask_at_turn`: at conversation turn N (N=3 default), inject an assistant-side prompt "May I have your email so we can follow up?" — model receives an instruction in its next system message to include the ask; when the reply contains an email, upsert lead.
  - Instructions tab (Step 8) gets the 3 new controls appended.
- **Backend endpoints**:
  - `GET /ai-assistants/{id}/analytics` — returns the KPIs + top questions.
- **Layered check** — the analytics query goes through `data_access.py`; no service commit needed for a pure read.

Out of scope:
- Deep conversation topic clustering (deferred).
- Sentiment / deflection scoring (deferred).
- CSV export of analytics (small follow-up).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_ai_assistants_lead_capture.py` | **NEW** — ALTER `tbl_ai_assistants` |
| `API/src/app/core/ai_assistants/models.py` | **EDIT** — add lead_capture cols |
| `API/src/app/core/ai_assistants/schemas.py` | **EDIT** — extend read/write shapes |
| `API/src/app/core/ai_assistants/runtime.py` | **EDIT** — email detection + turn-N ask hook |
| `API/src/app/core/ai_assistants/service.py` | **EDIT** — analytics + lead-capture wiring |
| `API/src/app/core/ai_assistants/data_access.py` | **EDIT** — analytics queries |
| `API/src/app/core/ai_assistants/router.py` | **EDIT** — `/analytics` endpoint |
| `APP/src/app/features/user/core/ai-assistants/analytics.page.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/analytics.page.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/ai-assistants.routes.ts` | **EDIT** — analytics route |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/instructions-tab.component.ts` | **EDIT** — add 3 lead_capture controls |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/instructions-tab.component.html` | **EDIT** |
| `APP/src/app/features/user/core/conversations/conversations.page.ts` (or filter component) | **EDIT** — add ai_widget filter |
| `API/tests/ai_assistants/test_lead_capture.py` | **NEW** |
| `API/tests/ai_assistants/test_analytics.py` | **NEW** |

**~15 files. ~550 lines.** Over but analytics + lead capture + inbox filter interlock and must ship together to make the assistant "useful" (leads captured, conversations reviewable, ROI visible).

## Plan

1. Migration adds 3 columns (nullable defaults) — reversible.
2. Email regex: reasonable pattern with case-insensitive flag; not RFC-perfect but good enough for lead capture.
3. Lead capture reuses existing `core/leads/service.create_or_get_lead` — if signature differs, plan phase inspects.
4. Analytics query is one JOIN + GROUP BY; index-supported via `(org_id, assistant_id, created_at DESC)` from Step 5.
5. Inbox filter: grep existing conversations page for channel filter to extend.
6. Analytics UI: two KPI cards + a plain table; matches existing analytics pages in campaigns / workflows.
7. Prettier on frontend files.

## DB changes / migrations

One ALTER on `tbl_ai_assistants` adding 3 nullable columns.

## Tests

- Email detection: user message "call me at bob@example.com" → lead created with email; conversation.contact_id set.
- Duplicate email: same email second time → same lead, no duplicate.
- Ask-at-turn: on turn 3, next assistant reply contains the ask (LLM prompt-side hook); when user replies with email, lead captured.
- `lead_capture_mode='off'` → no lead ever created.
- Analytics KPIs correct against seeded data.
- Top questions dedup by `LOWER(TRIM(...))` — "Hi" and "hi " count together.
- Inbox filter for `ai_widget` returns conversations.
- Assistant deleted: conversation still visible in inbox with "assistant removed" badge.

## Smoke

```
1. Enable lead_capture_mode=detect_email on an assistant.
2. From widget, chat: "Hi", "I'm at test@example.com, can you help me?"
3. Check /user/leads — new lead with source=ai_assistant.
4. Check /user/conversations filtered by channel=ai_widget — see the chat.
5. Add a note on the conversation from operator side — persists.
6. /user/ai-assistants/{id}/analytics → shows 1 message, cost > 0, top question "Hi".
```

## Risks

- Email regex false positives (e.g. inside a longer sentence with punctuation) — acceptable trade-off for v1.
- `tbl_conversations.metadata->>'assistant_id'` — check if conversations table has a metadata column; if not, add via this step or wire assistant_id differently.
- Lead capture during a live SSE stream: capture happens post-message, so no race with the streaming reply.

## Self-check (10 rules)

`core/ai_assistants/` extensions + `APP/`. ✓ Rule 2: analytics query scoped by org_id + assistant_id (both from JWT / path). ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar (Step 5). ✓ Permission enforced via `ai_assistants.view` on analytics. ✓ pack.yaml untouched. ✓ 15 files / ~550 lines — over but justified. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 16 — Inbox integration + analytics + auto-lead capture
Files: 15
Verify: AI conversations in inbox with channel filter; analytics KPIs correct;
        top-questions dedup; email detection creates lead; ask-at-turn works.
Tests: ~10 pytest + Angular cases.
Awaiting "proceed".
```
