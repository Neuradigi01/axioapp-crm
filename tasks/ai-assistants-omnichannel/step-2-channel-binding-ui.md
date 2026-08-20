# Step 2 — Channel binding UI in the Assistant editor

**Goal:** Add a compact "Channels" section to the AI Instructions tab (or a new "Deployment" section — Step 2's plan phase decides) with three checkboxes: **Website widget**, **WhatsApp**, **Email**. Values wire through the shared `AssistantFormStateService` and ship on the existing Save. On 409 `channel_already_bound`, show a clear inline error with a link to the other assistant.
**Status:** Pending
**Depends on:** Step 1 (backend column + PATCH support).

---

## Scope

In-scope:

- Add `bound_channels: AiAssistantChannel[]` to `AssistantFormState` in `form-state.service.ts`.
- Update `applyLoad()` / `applySaveResponse()` to populate from the read response.
- Update `buildUpdatePayload()` to include `bound_channels` in the PATCH body.
- Add channels section to `instructions-tab.component.html` (or split into a new tab if scope grows — decision in the Plan phase).
- Add channel checkbox toggle method to `instructions-tab.component.ts`.
- Handle 409 `channel_already_bound` in `ai-assistant-editor.page.ts`'s save error path — parse the response body's `other_assistant_id` + `other_assistant_name`, show a clear toast: *"WhatsApp is already handled by 'Support Bot'. Unbind it there first."*

Out of scope:

- Backend changes (Step 1 done).
- Preview pane changes (channel binding doesn't affect the live preview widget).
- Analytics of which channels are bound org-wide (future).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/ai-assistants/form-state.service.ts` | **EDIT** — add `bound_channels` to state + load/save |
| `APP/src/app/features/user/core/ai-assistants/ai-assistants-api.service.ts` | **EDIT** — add `bound_channels` field to `AiAssistantUpdatePayload` + `AiAssistant` interfaces |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/instructions-tab.component.ts` | **EDIT** — channel toggle method |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/instructions-tab.component.html` | **EDIT** — checkboxes section |
| `APP/src/app/features/user/core/ai-assistants/editor/ai-assistant-editor.page.ts` | **EDIT** — 409 handler in save() |

**~5 files, ~150 lines.**

## Plan

1. Confirm the section placement: probably a new `<h4>Deployment</h4>` block below AI Configuration, above Advanced. Not a new tab — the field is tiny.
2. Checkboxes are Tailwind-styled — match the existing "Output URL / email sanitiser" checkbox pattern in the Advanced section.
3. Copy for each channel:
   - **Website widget** — "Answer visitors on your website via the embed snippet."
   - **WhatsApp** — "Answer inbound messages on your WhatsApp Business number."
   - **Email** — "Auto-reply to emails sent to your connected mailbox."
4. Under each checkbox, a muted note if the channel isn't configured org-wide: e.g. WhatsApp checkbox shows *"⚠️ WhatsApp not connected — configure in Settings → Integrations."* Fetch org integrations state via existing `integrations` API (no new endpoint).
5. Save flow unchanged — just the payload grows. Toast on success (existing).
6. 409 error path: parse `err.error.detail` for `{reason: "channel_already_bound", channel, other_assistant_id, other_assistant_name}`; toast message references the other assistant name.

## Tests

Frontend E2E covered by manual smoke since this is UI:
- Load an existing assistant → checkboxes reflect current `bound_channels`.
- Toggle "WhatsApp" → header shows "Unsaved changes" → click Save → toast "Assistant saved." → reload editor → WhatsApp still checked.
- Create a second assistant → try to bind WhatsApp again → toast *"WhatsApp is already handled by 'Support Bot'. Unbind it there first."*
- Uncheck a previously-bound channel + Save → 200 (no conflict check on removal).
- API service unit-test — `AiAssistantUpdatePayload.bound_channels` optional, serializes as JSON array.

## Self-check checklist

- [ ] Rule 4 (dynamic forms) — checkboxes are static UI (only 3 channels; not user-defined). Not a form-fields fetch scenario. OK.
- [ ] Rule 8 (small step) — 5 files, ~150 lines.
- [ ] Frontend layer discipline — form-state.service is the store; component reads/writes via it. Consistent with existing tabs.
- [ ] Standard warning banner pattern reused for the "channel not connected" hint.

## Stop-and-report template

> Files changed: `<list>`
> What you can verify: Open an assistant, toggle Website widget + WhatsApp checkboxes, Save. Reload editor — checkboxes still checked. Create a second assistant, try to bind WhatsApp — see the "already handled by X" toast.
> Tests added: 1 API service unit test + 4 manual smoke assertions.
> Self-check: pass · pass · pass · pass.
> Awaiting your 'proceed'.
