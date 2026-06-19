# Step 19 — AI agent wiring on WhatsApp

**Goal:** Wire the orphan `tbl_conversations.ai_handling` field to the existing `core/ai/` module. When AI handling is enabled on a conversation, inbound messages route through the AI agent → response sent back through WhatsApp adapter as an outbound message. Handover to human on confidence threshold / explicit request / manual override.
**Status:** Pending
**Depends on:** Step 17 (automation pipeline), Step 18 (assignment fallback on handover).

---

## Scope

In-scope:
- **Wire** existing `tbl_conversations.ai_handling` field — currently unwired anywhere.
- New service `ai_handler.py` (under `core/integrations/whatsapp/` glue, with consumer-facing logic in `core/ai/whatsapp_integration.py`):
  - Inbound message + conversation context → AI module → response text + suggested actions (handoff / tag / escalate).
  - Send response back through WhatsApp adapter.
  - Track AI vs human responses in conversation analytics.
- Handover triggers:
  - User explicitly asks for human ("talk to person", "agent please", "इंसान से बात")
  - AI confidence below configurable threshold
  - Conversation tagged for handover
  - Manual override via `PATCH /conversations/{id}/ai-handling`
- Endpoints:
  - `PATCH /api/v1/conversations/{id}/ai-handling` — toggle per conversation
  - `GET /api/v1/whatsapp/ai/settings` — org-wide defaults (auto-enable for new convos, escalation threshold)
  - `PATCH /api/v1/whatsapp/ai/settings`
- Conversation header toggle (visible to staff with `conversations.write`).
- Visual marker on AI-generated messages (small "🤖 AI" badge).
- Automation sub-page → "AI Settings" tab.

Out of scope:
- AI model selection (use whatever `core/ai/` is configured with) — see "Pre-step decision" below.
- AI training / fine-tuning UI.
- Cross-channel AI (SMS/Email) — WhatsApp only for this step.

## Pre-step decision (escalate to user)

- **Which AI model backs WhatsApp auto-responses?** Recommend same as the rest of `core/ai/`. Confirm.
- **Default opt-in or opt-out for new conversations?** Recommend opt-in per conversation; org-wide default toggle for power users.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/ai/whatsapp_integration.py` | **NEW** AI ↔ WhatsApp glue |
| `API/src/app/core/integrations/whatsapp/ai_handler.py` | **NEW** dispatch + handover logic |
| `API/src/app/core/integrations/whatsapp/models.py` | Add org-wide AI settings columns or new table |
| `API/alembic/versions/<ts>_whatsapp_ai_settings.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Route inbound to AI when ai_handling=true |
| `API/src/app/core/integrations/whatsapp/automation_router.py` | AI settings endpoints |
| `API/src/app/core/conversations/router.py` | Add `PATCH /{id}/ai-handling` |
| `APP/.../whatsapp/automation/ai-settings.component.ts` | **NEW** |
| `APP/.../conversations/header/ai-handling-toggle.component.ts` | **NEW** |
| `APP/.../conversations/thread/message-bubble.component.ts` | Render 🤖 AI badge on AI messages |
| `API/tests/integrations/test_whatsapp_ai.py` | **NEW** |

**~11 files. ~700 lines.**

## Plan

1. Migration: org-wide AI settings (confidence threshold, default-enable, handover keywords).
2. AI integration: send conversation history + last inbound + org system prompt to `core/ai/`; receive response + confidence + suggested actions.
3. Handover detection: regex/keyword scan for explicit asks; confidence threshold; tag check.
4. On handover: set `ai_handling=false`, tag `ai_escalated`, run assignment engine (Step 18).
5. Marker: store `meta.author = 'ai'` on AI-generated outbound; bubble component reads.
6. Frontend toggle: simple switch; calls PATCH; subscribes to status.
7. Tests: full conversation cycle with AI; handover triggers; confidence threshold; manual override mid-conversation.

## DB changes / migrations

Org-wide AI settings: `confidence_threshold FLOAT DEFAULT 0.6`, `default_enable_new_conversations BOOL DEFAULT FALSE`, `handover_keywords TEXT[]`.

## Tests

10 pytest + 3 Jest.

## Smoke

```
1. Enable AI org-wide. Toggle a conversation's ai_handling on.
2. Inbound "What's your business hours?" → AI replies with hours from Step 11 profile within ~2s.
3. AI message bubble shows 🤖 AI badge.
4. Inbound "I want to talk to a person" → handover triggers: AI off, tag ai_escalated, assignment engine picks staff.
5. Low-confidence AI response: simulate confidence < 0.6 → escalate same path.
6. Staff toggles AI back on mid-conversation → next inbound routes to AI again.
7. AI handover doesn't loop on its own outbound messages.
8. Audit log per AI message + handover.
```

## Risks

- AI hallucination on price / availability — system prompt must include "do not commit to prices, refer to human if uncertain."
- Latency: AI response > 3s causes customer frustration. Show typing indicator if Meta supports; else accept.
- Token costs — cap conversations per day if budget concern.

## Self-check (10 rules)

All `core/integrations/whatsapp/` + new `core/ai/whatsapp_integration.py`. ✓ Rule 1. org_id + RLS preserved. ✓. No custom-field changes. ✓. Settings form static. ✓ N/A. New tab under existing sub-page. ✓. Existing `whatsapp.automation.manage`. ✓. pack.yaml untouched. ✓. 11 files / ~700 lines. ✓ at edge. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 19 — AI agent wiring on WhatsApp
Files: 11
Verify: AI replies to inbound; handover on keyword + confidence + tag + manual; AI badge in bubble; audit log.
Tests: 10 pytest + 3 Jest.
Phase 6 (Automation) complete. Next: Step 20 — conversation analytics.
Awaiting "proceed".
```
