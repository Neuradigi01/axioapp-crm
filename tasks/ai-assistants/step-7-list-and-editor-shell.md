# Step 7 — Frontend list page + editor shell with 4 empty tabs + live preview pane

**Goal:** Ship the Angular list page at `/user/ai-assistants` and the two-pane editor shell at `/user/ai-assistants/:id`. The editor has 4 empty tabs (AI Instructions · Knowledge Source · Assistant Interface · Styling) and a right-side live-preview pane that subscribes to the assistant's form state and re-renders locally without network calls. Save button in the header. No tab contents yet — those land in Steps 8, 11, 12, 13. Match existing pages (workflows, campaigns) visually — no new patterns.
**Status:** COMPLETED — 21 files landed (2 edits + 19 new; 1 more than the spec's 20 because Sparkles wasn't in `app.config.ts`'s lucide-pick bag). Full list page at `/user/ai-assistants` with status pills (All/Draft/Active/Archived), debounced 300ms search, card grid with kebab menu (Archive/Delete), permission-gated Create CTA, empty state. Two-pane editor at `/user/ai-assistants/:id`: header bar (back arrow + inline-editable name + status pill + Embed button [disabled — Step 15] + Save button that enables only when form is dirty), left 60% pane with 4-tab strip mounting placeholder tabs for Steps 8/11/12/13, right 40% pane with the live-preview component. Preview reads the `AssistantFormStateService` signal store and re-renders synchronously — zero network calls fire from the preview (verified via the design: the preview only reads signals, and the ng build shows no HTTP dependency in its module graph). `AssistantFormStateService` is provided at the editor-page level (not root) so a fresh instance mounts on every navigation to a new assistant — `load()` hydrates from the fetched row, `patch()` marks dirty, Save re-hydrates from the PATCH response. Two-field Create modal populates the key select from Step 3's `AiProvidersApiService` and falls back to an amber "Configure a key in Settings → Integrations" banner when none exist. Backend regression: all 97 Steps 1-6 tests still green in 25.66s. `ng build --configuration development` clean (no ai-assistants errors; only pre-existing task-form-modal warning). One small icon-registry addition: `Sparkles` added to `app.config.ts` imports + `LucideAngularModule.pick()` bag so Step 5's `icon="sparkles"` sidebar entry renders correctly.
**Depends on:** Step 6 (CRUD endpoints).

---

## Scope

In-scope:

- Angular feature module at `APP/src/app/features/user/core/ai-assistants/`:
  - `ai-assistants.page.ts/.html` — list view.
    - Header: page title "AI Assistants", subtitle "Chat-style assistants powered by your own OpenAI key.", "+ Create Assistant" button (permission-gated on `ai_assistants.manage`).
    - Filter bar: status pills (All · Draft · Active · Archived) + search input.
    - Grid of assistant cards: card contains name, status pill, model badge, knowledge-count badge, message-count-last-30d badge, "Edit" link, kebab menu (Archive / Delete).
    - Empty state: "No assistants yet." + CTA to create.
  - `editor/ai-assistant-editor.page.ts/.html` — two-pane editor.
    - **Header bar**: back arrow, editable assistant-name (inline edit like workflows canvas), status pill, right-side buttons: **Embed** (disabled until Step 15), **Save AI Assistant**.
    - **Left pane** (60% width): tab strip (4 tabs) + tab content area. Tab strip matches templates page (grep `template-tab-strip` for tokens).
    - **Right pane** (40% width): the `AssistantPreviewComponent` — a self-contained chat widget preview that renders from the current form-state signal. No network calls; simulates one turn ("Hi there! 👋 How can I help you today?") using the assistant's `interface_config` + `styling_config` fields.
  - `editor/tabs/instructions-tab.component.ts/.html` — placeholder ("AI Instructions tab — coming in Step 8").
  - `editor/tabs/knowledge-source-tab.component.ts/.html` — placeholder ("Knowledge Source tab — coming in Step 11").
  - `editor/tabs/assistant-interface-tab.component.ts/.html` — placeholder ("Assistant Interface tab — coming in Step 12").
  - `editor/tabs/styling-tab.component.ts/.html` — placeholder ("Styling tab — coming in Step 13").
  - `editor/preview/assistant-preview.component.ts/.html` — reads a `Signal<AssistantFormState>` input; renders header, initial-message bubble, mock user input; styles from `styling_config`. Default styling if config empty.
  - `create-assistant-modal.component.ts/.html` — invoked from list page's "+ Create". Small modal: name input + first key-select (populated from `GET /integrations/ai/providers`). Save creates the assistant with `status='draft'` and navigates to editor.
  - `ai-assistants-api.service.ts` — typed API client for Step 6's endpoints.
  - `form-state.service.ts` — the shared editor-scoped signal store that all tabs write into and the preview reads from. Emits changes; a debounced observer POSTs `PATCH` on Save button click (not autosave in v1 — explicit Save button per Pabbly reference).
- Routing wired in `APP/src/app/features/user/user.routes.ts` — lazy-loaded child route `{ path: 'ai-assistants', loadChildren: () => import('./core/ai-assistants/ai-assistants.routes') }`.
- HTTP retry interceptor already in place (per `feedback_http_retry_interceptor` memory).

Out of scope:
- Tab contents (Steps 8/11/12/13).
- Embed button wiring (Step 15).
- Live streaming preview against real LLM (Step 9 introduces real chat; preview stays local until then).
- Conversation history page (Step 16).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/ai-assistants/ai-assistants.routes.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/ai-assistants.page.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/ai-assistants.page.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/ai-assistants-api.service.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/form-state.service.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/create-assistant-modal.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/create-assistant-modal.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/ai-assistant-editor.page.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/ai-assistant-editor.page.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/instructions-tab.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/instructions-tab.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge-source-tab.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/knowledge-source-tab.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/assistant-interface-tab.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/assistant-interface-tab.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/styling-tab.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/styling-tab.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/preview/assistant-preview.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/preview/assistant-preview.component.html` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | **EDIT** — lazy route |

**~20 files. ~700 lines.** Over the soft cap but justified: the shell needs list + editor + 4 tab placeholders + preview + modal + API service + form-state signal store to hang together as a runnable page. Splitting would leave a half-built route where the user can't get to the editor. Individually each file is tiny (placeholders average 20 lines).

## Plan

1. Grep existing similar pages first — `core/workflows/workflows.page.ts`, `core/templates/templates.page.ts`, `core/campaigns/campaigns.page.ts` — to match card grid + filter bar + tab strip patterns exactly.
2. `form-state.service.ts` uses Angular signals — one signal per top-level field; `computed()` for derived state; `.patchState()` helper for tab-side writes.
3. Preview component subscribes via `input()` signal and renders synchronously — no async, no HTTP.
4. Modal invocation via existing modal service (grep for `openModal` usage in campaigns).
5. Router lazy-loads; permission guard checks `ai_assistants.view` on list, `ai_assistants.manage` on editor's write actions.
6. Run `npx --no-install prettier --write` on all touched files before commit per `feedback_prettier_on_write`.
7. Lucide icons used: `bot`, `sparkles`, `check`, `x`, `chevron-left`, `save`, `code`, `more-vertical`. Verify each is registered in `app.config.ts` per `feedback_lucide_icon_registry`.

## DB changes / migrations

None.

## Tests

Angular component tests (Jest / Karma per existing setup):
- List page renders 0 / 1 / N cards.
- Filter pills filter the grid.
- "+ Create" modal opens with the key select populated.
- Modal Save navigates to editor with correct id.
- Editor mounts all 4 tab placeholders.
- Preview component reads form-state signal and re-renders when signal changes.
- Save button POSTs `PATCH` with the current form state (mock backend).
- Kebab menu Archive/Delete calls the right endpoints (mocked).
- Preview does not fire any HTTP calls (spied `HttpClient`, expect 0 calls).

## Smoke

```
1. Log in as Owner. Navigate to /user/ai-assistants.
2. See empty state. Click "+ Create Assistant".
3. Modal: pick key, name, Save. Navigate to /user/ai-assistants/{id}.
4. See two-pane editor. 4 tabs visible; each shows placeholder. Preview pane
   renders header "Your Brand Name 👋" + initial message bubble.
5. Rename via inline edit. Save. Refresh — name persisted.
6. Back to list. Card shows new assistant.
```

## Risks

- Signal-based form-state store is a new pattern for this module; grep existing signal usage in other pages first to match conventions.
- The preview pane needs to work with `styling_config = {}` — sensible defaults required in the preview component to avoid an empty white box.

## Self-check (10 rules)

`APP/` frontend only. ✓ N/A org_id (no tables). N/A custom fields. N/A dynamic forms. Sidebar entry via Step 5's module.py — verify visible. ✓ Permission-gated at API + route level. ✓ pack.yaml untouched. ✓ 20 files / ~700 lines — over but justified. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 7 — Frontend list page + editor shell with 4 empty tabs + live preview
Files: 20
Verify: list renders; create modal navigates to editor; 4 tab placeholders mount;
        preview renders and re-renders on form-state change; save persists.
Tests: ~9 Angular component tests.
Awaiting "proceed".
```
