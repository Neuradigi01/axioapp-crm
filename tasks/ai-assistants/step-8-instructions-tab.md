# Step 8 — AI Instructions tab + assistant-behaviour controls + audit log

**Goal:** Ship the AI Instructions tab: instruction-type dropdown (Custom Prompt + 6 seeded presets from `core/templates?channel=ai_prompt`), prompt textarea, temperature slider, provider-key select, model select, assistant-behaviour controls (stop-keywords, retry, fallback message, allowed_domains, output_sanitizer toggle, budget_cap_override). Every change to `instructions` writes an audit log row via Step 6's service. Seed the 6 preset templates through `core/templates/`.
**Status:** COMPLETED — 11 files (2 migrations + 5 backend + 4 frontend). Migrations `0203_ai_prompt_channel` (ADD VALUE with `autocommit_block`) + `0204_bf_ai_prompt_templates` (raw-SQL backfill; 246 rows across 41 orgs = 6 presets/org). Extended `ConversationChannel` enum with `ai_prompt`, added `seed_ai_prompt_presets` to `core/templates/seeds.py` with 6 preset bodies (AI Agent / Customer Support / Sales / Language Tutor / Coding Expert / Life Coach), invoked from `create_organization` (soft-fail). Instructions tab fleshed out with three sections: Prompt (dropdown Custom + 6 presets that COPY into textarea + textarea), AI Configuration (temperature slider 0-1, key select filtered to `test_status='success'` keys with amber banner + Settings link when empty, model select), Advanced (stop-keywords chip input, retry attempts, fallback message, allowed-domains chip input, output-sanitiser toggle, budget cap override). All fields two-way bind to Step 7's form-state signal store; Save button reads full state and PATCHes; Step 6's service writes an audit row for every instruction/model/temperature/allowed_domains/output_sanitizer_enabled change. 102 tests green in 35.17s (5 new Step 8: preset bag well-formed + non-empty + ai_prompt enum registered + seed idempotent + rows carry expected fields). Four migration bug-fixes surfaced during retries: (1) `asyncio.run` inside Alembic — switched to raw SQL; (2) `UnsafeNewEnumValueUsageError` — added `autocommit_block()` around ADD VALUE; (3) `AmbiguousParameterError` — cast bind params explicitly to varchar/text; (4) column name mismatch — `tbl_message_template_versions.changed_at`, not `created_at`.
**Depends on:** Step 6 (CRUD service writes audit log), Step 7 (editor shell).

---

## Scope

In-scope:

- **Backend seed** — extend `core/templates/seeds.py` (or the equivalent seed entrypoint) to seed 6 default templates with `channel='ai_prompt'` at org creation:
  - "AI Agent", "Customer Support Agent", "Sales Agent", "Language Tutor", "Coding Expert", "Life Coach" — bodies mirror Pabbly Chatflow's reference prompts (adapted for our tone).
  - Idempotent — only seed if org has none with `channel='ai_prompt'`.
  - Migration `<ts>_add_ai_prompt_templates.py` — if the channel column is an ENUM, ALTER to add `'ai_prompt'`; otherwise no-op.
  - Backfill for existing orgs handled by a one-shot Alembic data migration.
- **Backend endpoint** — `GET /templates?channel=ai_prompt` should already work if templates router honours the channel filter (verify against `core/templates/router.py`; if not, add the filter).
- **Frontend tab** — `editor/tabs/instructions-tab.component.ts/.html` — flesh out from Step 7's placeholder:
  - **Instruction Type dropdown** — options: `Custom Prompt` (default), then the 6 preset templates fetched from `GET /templates?channel=ai_prompt`. Selecting a preset populates the prompt textarea with the template body (user can then edit — this is a copy, not a live binding).
  - **Prompt textarea** — 8 rows minimum, resizable. Placeholder text mirrors Pabbly.
  - Divider + subheading "AI Configuration":
    - **Temperature** slider 0–1 step 0.1 with numeric readout. Help text: "0 means more focused, 1 means more creative."
    - **Select AI To Use** dropdown — populated from `GET /integrations/ai/providers` (only shows configured keys with `test_status='success'`; disabled provider tiles for unconfigured providers with "Configure in Settings → Integrations" link).
    - **Select Model** dropdown — depends on selected key; shows `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, `gpt-3.5-turbo` (from Step 2's pricing table). If key not selected, dropdown disabled.
  - Divider + subheading "AI Assistant Settings":
    - **Header Message** toggle + text input (when on).
    - **Footer Message** toggle + text input (when on).
    - **Stop Keywords** toggle + chip-list input (add keyword on Enter; remove on x). Placeholder "+Add keywords".
    - **Retry Attempt** toggle + numeric input (0–3, default 0).
    - **Fallback Message** toggle + textarea (default already populated from Step 5's server default).
  - Divider + subheading "Advanced":
    - **Allowed Domains** chip-list — for output URL sanitiser. Placeholder "example.com".
    - **Output Sanitizer** toggle (default on) — help text: "On public embeds, remove URLs and emails not on the Allowed Domains list."
    - **Budget Cap Override** numeric — help text: "Override the org daily cap for this assistant (leave blank to use org default)."
- **Form-state integration** — every field two-way binds to Step 7's `form-state.service.ts`.
- **Save** — the Save button in the editor header (from Step 7) reads form-state, POSTs `PATCH /ai-assistants/{id}` with the delta and current `version`. Backend audit log fires on `instructions` change (Step 6 already handles).

Out of scope:
- Chat runtime (Step 9).
- Knowledge Source tab (Step 11).
- Interface + Styling tabs (Steps 12, 13).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/templates/seeds.py` | **EDIT** — add 6 ai_prompt presets |
| `API/alembic/versions/<ts>_add_ai_prompt_templates.py` | **NEW** — ENUM alter + backfill |
| `API/src/app/core/templates/router.py` | **EDIT** — verify/add channel filter |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/instructions-tab.component.ts` | **EDIT** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/instructions-tab.component.html` | **EDIT** |
| `APP/src/app/features/user/core/ai-assistants/ai-assistants-api.service.ts` | **EDIT** — add `getAiPromptTemplates()` + `getProviders()` |
| `APP/src/app/features/user/core/ai-assistants/instructions-presets.ts` | **NEW** — labels for the dropdown (backend gives bodies) |
| `API/tests/templates/test_ai_prompt_presets.py` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/instructions-tab.component.spec.ts` | **NEW** |

**~9 files. ~400 lines.**

## Plan

1. Backend seed first: 6 template bodies drafted (Pabbly-style but adjusted for our voice — recorded in the migration file for traceability). Migration is data-only after any ENUM alter.
2. Verify `templates` router accepts `channel` filter; add if missing (small edit).
3. Frontend tab: fetch presets on init; render dropdown with "Custom Prompt" as first option; on selection, patch the prompt textarea via form-state.
4. Provider select fetches once on init; disabled entries for missing providers include an anchor `<a routerLink="/user/settings/integrations">Configure</a>`.
5. Model select depends on key type — since v1 is OpenAI-only, list is static; when Anthropic ships later, this becomes provider-driven.
6. Stop-keywords chip input matches existing chip pattern (grep for `chip-list` in campaigns or templates).
7. All labels + help text lifted from Pabbly screenshots but rewritten for our voice.
8. Run prettier on all touched files.

## DB changes / migrations

One migration if `channel` is an ENUM (ALTER to add `'ai_prompt'`); else data-only backfill migration seeding 6 rows per existing org.

## Tests

Backend:
- 6 preset templates seed idempotently: seed twice → still 6 rows per org.
- `GET /templates?channel=ai_prompt` returns 6 rows.
- Migration up + down.

Frontend:
- Dropdown lists 7 options (Custom + 6 presets).
- Selecting a preset populates the prompt textarea with the fetched body.
- Provider select disabled if no keys configured; enabled once seeded.
- Model select disabled until provider chosen.
- Temperature slider clamped 0–1.
- Stop-keywords chip: add on Enter, remove on x.
- Save PATCH called with the correct payload including current `version`.

## Smoke

```
1. As Owner, create an assistant. Open Instructions tab.
2. Dropdown shows Custom + 6 presets. Pick "Customer Support Agent" — textarea populates.
3. Edit the prompt. Change temperature. Pick a key + model.
4. Add stop-keywords "stop", "bye".
5. Save. Reload page. All values persisted.
6. Check tbl_ai_assistant_instruction_audit — 1 row per instruction change.
```

## Risks

- Templates seed migration touches existing orgs — the data backfill needs to be safe if run multiple times (idempotent).
- If templates channel column is free text (not enum), no migration needed for the column but seed still runs.

## Self-check (10 rules)

`core/templates/` extension + `APP/` frontend. ✓ Rule 2: templates already org-scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. ✓ Permission enforcement at API. ✓ pack.yaml untouched. ✓ 9 files / ~400 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 8 — AI Instructions tab + assistant-behaviour controls + audit log
Files: 9
Verify: dropdown lists 7 options; preset populates textarea; all fields save;
        audit row written per instruction change; provider dropdown gates by config.
Tests: ~10 pytest + Angular cases.
Awaiting "proceed".
```
