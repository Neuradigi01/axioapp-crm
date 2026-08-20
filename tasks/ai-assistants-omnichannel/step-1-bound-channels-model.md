# Step 1 — `bound_channels` column + service-layer uniqueness + PATCH wiring

**Goal:** Extend `tbl_ai_assistants` with a `bound_channels JSONB` column so each assistant declares which channels (`ai_widget`, `whatsapp`, `email`) it should auto-answer on. Enforce "one assistant per (org, channel)" at the service layer. Wire the field into the existing `AiAssistantUpdate` schema so the current PATCH endpoint just works — no new route needed.
**Status:** COMPLETED — migration `0209_ai_bound_channels` applied via `run.cmd upgrade`. `AiAssistantChannel` enum + `bound_channels` JSONB column landed on `AiAssistant`. `AiAssistantUpdate` + `AiAssistantRead` schemas extended. Service pre-flight rejects channel-double-bind with 409 `channel_already_bound`. DAL exposes `find_active_assistant_bound_to_channel` using JSONB `?` operator over the new GIN index. Import smoke green (`AiAssistantChannel.whatsapp`, `hasattr(AiAssistant, "bound_channels")`, `hasattr(data_access, "find_active_assistant_bound_to_channel")` all true). 8 tests written (3 pure Pydantic + 5 DB-integration) — not yet executed (deferred to batched pytest run per project convention).
**Depends on:** — (first step)

---

## Scope

In-scope:

- Migration `<ts>_ai_assistants_bound_channels.py` — ALTER `tbl_ai_assistants` ADD COLUMN `bound_channels JSONB NOT NULL DEFAULT '[]'::jsonb`. Add GIN index `ix_ai_assistants_bound_channels_gin ON tbl_ai_assistants USING gin (bound_channels)`. Reversible.
- Model — `AiAssistant.bound_channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))`.
- Enum `AiAssistantChannel` in `core/ai_assistants/models.py` — `ai_widget | whatsapp | email` (extensible without migration).
- Schema — add `bound_channels: list[AiAssistantChannel] | None = None` to `AiAssistantUpdate` (existing schema, `extra="forbid"`). Add `bound_channels: list[AiAssistantChannel]` to `AiAssistantRead`.
- Service — `update_assistant` gets a new pre-flight check: **before flush**, if `payload.bound_channels` is set and adds a channel not previously bound, query `tbl_ai_assistants WHERE org_id=$1 AND id != $2 AND status='active' AND bound_channels ? :channel` — reject with `HTTPException(409, {"reason": "channel_already_bound", "channel": ch, "other_assistant_id": <id>, "other_assistant_name": <name>})` if any hit.
- Data access — `data_access.find_assistant_bound_to_channel(db, org_id, channel, exclude_id) -> AiAssistant | None`.

Out of scope:

- UI (Step 2).
- Auto-populate `bound_channels=['ai_widget']` for existing assistants — deliberately empty by default; operators opt in per channel.
- Inbound dispatch that reads the column (Step 5).
- Any change to `AiAssistantCreate` — operators bind channels post-create via the editor.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_ai_assistants_bound_channels.py` | **NEW** |
| `API/src/app/core/ai_assistants/models.py` | **EDIT** — add `AiAssistantChannel` enum + `bound_channels` column |
| `API/src/app/core/ai_assistants/schemas.py` | **EDIT** — add field to `AiAssistantUpdate` + `AiAssistantRead` |
| `API/src/app/core/ai_assistants/service.py` | **EDIT** — pre-flight channel-conflict check in `update_assistant` |
| `API/src/app/core/ai_assistants/data_access.py` | **EDIT** — `find_assistant_bound_to_channel` query |
| `API/tests/ai_assistants/test_bound_channels.py` | **NEW** |

**~6 files, ~250 lines.**

## Plan

1. Migration writes ALTER + GIN index + backfill (all rows get `[]` via `server_default`; no explicit UPDATE needed).
2. `AiAssistantChannel(str, Enum)` — three values matching the existing `ConversationChannel` enum keys.
3. `AiAssistantUpdate.bound_channels: list[AiAssistantChannel] | None = None` — Pydantic dedups + validates each entry against the enum. `extra="forbid"` on the schema means the frontend can't sneak in unknown channels.
4. Service pre-flight: only fires if payload includes `bound_channels`. Compares old vs new; only NEW channels trigger the conflict check.
5. On conflict → 409 body includes the other assistant's id + name so the UI toast is actionable ("Support Bot already handles WhatsApp — unbind it there first").
6. Existing `_apply_updates` handles the column write through `model_dump(exclude_unset=True)` — no code change there.

## DB changes / migrations

```sql
ALTER TABLE tbl_ai_assistants
  ADD COLUMN bound_channels JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX ix_ai_assistants_bound_channels_gin
  ON tbl_ai_assistants USING gin (bound_channels);
```

Down: drop index, drop column.

## Tests (`test_bound_channels.py`)

- Migration up + down clean.
- Fresh row has `bound_channels=[]`.
- PATCH with `bound_channels=["ai_widget"]` persists.
- PATCH with `bound_channels=["ai_widget", "whatsapp"]` persists both.
- PATCH with `bound_channels=["nonsense"]` returns 422 (Pydantic enum validation).
- Two assistants in same org, first binds `["whatsapp"]`, second tries `["whatsapp"]` → 409 with `channel_already_bound` reason + other assistant's id/name.
- Same conflict check does NOT fire if the second assistant is `status='archived'`.
- Same conflict check does NOT fire if I re-PATCH my own assistant with an unchanged binding list.
- Cross-org: org A binds WhatsApp, org B binds WhatsApp — no conflict (org-scoped).

## Self-check checklist

- [ ] Rule 2 (`tbl_` prefix + `org_id`) — modifying existing `tbl_ai_assistants`, no new tables.
- [ ] Rule 8 (small step) — 6 files, ~250 lines. Under the ceiling.
- [ ] Router → Service → DAL — no router change (existing PATCH handles it); service does the check; DAL does the read.
- [ ] Migration reversible.
- [ ] Tests proportional (7 assertions, one file).

## Stop-and-report template

> Files changed: `<list>`
> What you can verify: PATCH `/api/v1/ai-assistants/{id}` with `{"version": N, "bound_channels": ["whatsapp"]}` returns 200; second assistant PATCH with same channel returns 409 with `channel_already_bound`.
> Tests added: `test_bound_channels.py` (7 assertions).
> Self-check: pass · pass · pass · pass · pass.
> Awaiting your 'proceed'.
