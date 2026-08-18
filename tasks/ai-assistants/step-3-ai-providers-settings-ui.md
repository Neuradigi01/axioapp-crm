# Step 3 — Settings → Integrations "AI Providers" section UI

**Goal:** Ship the operator-facing UI for BYOK OpenAI keys + org budget cap inside Settings → Integrations. Add key (OpenAI only in v1), test, delete (with reassign flow), and daily/monthly USD cap controls. Match existing Settings tabs' visual language exactly — no new component patterns.
**Status:** Pending
**Depends on:** Step 1 (endpoints), Step 2 (test endpoint calls real OpenAI).

---

## Scope

In-scope:

- New section inside the existing Integrations page (or a new tab, depending on the page's shape — Step 1's Plan phase determines):
  - **AI Providers** heading with subheading "Bring your own OpenAI API key. Anthropic, Google, and OpenRouter coming soon."
  - **Provider tile** row per stored key: OpenAI logo · "Default" (label) · `sk-…AB12` (masked last-4) · test status pill (`untested` grey / `success` green / `failed` red with tooltip on hover showing `test_last_error`) · **Test** button · **Delete** button.
  - **+ Add Key** button opens a modal:
    - Provider select (OpenAI selected + disabled; other three disabled with "Coming soon" tag — matches Pabbly screenshot).
    - Label input (optional, defaults to "Default").
    - API Key input (`type="password"`, autocomplete off) with visibility toggle icon.
    - **Test** button — calls `POST .../providers/{tmp}/test` **after** save (test-on-save). Displays result inline.
    - Save button — POSTs, closes modal on success, refreshes list.
  - **Delete flow** — if response is 409 with reference list, opens a **Reassign modal** listing referencing assistants and a "Move all to another key" select. Two buttons: **Reassign & Delete** (chains `/reassign` then `DELETE`), **Cancel**.
  - **Budget cap card** below the provider list:
    - Two inputs — Daily cap USD (default 10.00), Monthly cap USD (default 200.00). Numeric with step 0.01.
    - Read-only rollups — "Spent today: $X.YZ / $10.00" + "Spent this month: $X.YZ / $200.00" progress bars.
    - Save button on change (debounced).
- Angular components under `APP/src/app/features/user/core/settings/tabs/ai-providers/` — folder because there are 4 sub-components (list · add-modal · reassign-modal · budget-card):
  - `ai-providers-section.component.ts/.html`
  - `add-key-modal.component.ts/.html`
  - `reassign-modal.component.ts/.html`
  - `budget-cap-card.component.ts/.html`
- API service `APP/src/app/features/user/core/settings/tabs/ai-providers/ai-providers-api.service.ts` — thin wrapper over the endpoints from Step 1.
- Wire the new section into the existing Integrations page (`APP/src/app/features/user/core/settings/tabs/embed-integrations-tab.component.ts` or the equivalent page — Step 3's Plan phase confirms the exact insertion point).
- Route: no change — sits inside the existing `/user/settings/integrations` route.

Out of scope:
- Assistant CRUD UI (Step 7+).
- Model-tier picker per assistant (Step 8).
- Provider-side model catalog fetch (v1 uses hardcoded list per Step 2 pricing table).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/settings/tabs/ai-providers/ai-providers-section.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/ai-providers-section.component.html` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/add-key-modal.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/add-key-modal.component.html` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/reassign-modal.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/reassign-modal.component.html` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/budget-cap-card.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/budget-cap-card.component.html` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/ai-providers-api.service.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/integrations-tab.component.ts` (or existing tab file) | **EDIT** — mount section |

**~10 files. ~450 lines.** Just under the split threshold. Modals stand alone as their own components to avoid the parent HTML blowing past readability.

## Plan

1. Inspect the existing Integrations tab file first to confirm the mount point and visual pattern.
2. Wire the API service against Step 1's endpoints; types are typed DTOs mirroring the Pydantic read schemas.
3. Component tokens strictly reuse: `rounded-lg bg-surface border border-subtle` for cards, `bg-accent px-3 py-1.5 text-sm font-semibold text-white` for primary buttons, `border-subtle text-default hover:bg-surface-2` for secondary, form inputs `rounded-lg border border-subtle bg-surface px-3 py-1.5 text-sm focus:border-muted focus:outline-none focus:ring-1 focus:ring-accent`, labels `block text-xs font-medium text-muted`.
4. Modals mount via existing modal-service pattern used in campaigns / templates (grep for `openModal(` to find the shared modal wrapper).
5. Full key **never** rendered after save — after POST returns, the modal shows only the masked last-4 and closes.
6. Standard amber warning banner (per `feedback_standard_warning_banner_pattern`) shown above budget-cap card when spent > 80% of cap.
7. Run `npx --no-install prettier --write <touched files>` before commit per `feedback_prettier_on_write`.

## DB changes / migrations

None.

## Tests

Angular component tests:
- List renders 0 / 1 / N keys correctly.
- Add modal disables OpenAI select (selected) and shows "Coming soon" tag on the other three.
- Save-then-test flow: save succeeds → test button appears → click → status pill updates.
- Delete on referenced key surfaces Reassign modal with the assistants list.
- Reassign modal Save calls both endpoints in order.
- Full API key never appears in the DOM after modal closes (queried via `fixture.debugElement.query`).
- Budget cap Save is debounced (fake timer).
- Progress bar renders correct percentage at 0 / 50 / 100 / >100%.

## Smoke

```
1. Log in as Owner. Navigate to Settings → Integrations.
2. See AI Providers section. Click + Add Key.
3. Paste a real OpenAI key. Save. See row with masked last-4.
4. Click Test. See green success pill.
5. Change Daily cap to 5.00. See Save. Refresh. Value persisted.
6. Delete key. Confirm. Row gone.
```

## Risks

- If the existing Integrations page is a sprawling monolith, the section insertion needs care not to break siblings. Plan phase reads the file first.
- Reassign modal shows assistants that don't exist yet (Step 5 introduces `tbl_ai_assistants`). Until Step 5, the reference count is always 0, so the modal never appears — acceptable for the step-by-step flow.

## Self-check (10 rules)

`APP/` frontend only. ✓ N/A org_id (no tables). N/A custom fields. N/A dynamic forms. Wires into existing Settings sidebar entry. ✓ Guarded by `ai_providers.manage` at API layer. ✓ pack.yaml untouched. ✓ 10 files / ~450 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 3 — Settings → Integrations AI Providers section UI
Files: 10
Verify: add/test/delete/reassign flows against a live backend; budget-cap updates persist.
Tests: ~9 Angular component tests.
Awaiting "proceed".
```
