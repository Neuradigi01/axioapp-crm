# Step 12 — Assistant Interface tab UI

**Goal:** Ship the Assistant Interface tab. Fields per Pabbly reference: Header display heading, subheading, initial messages (up to 2 chat bubbles), "Powered by" toggle, footer text + link. All writes flow through the Step 7 form-state signal; the preview pane re-renders live. Persist under `assistant.interface_config` JSONB (already added in Step 5).
**Status:** Pending
**Depends on:** Step 7 (editor shell + form-state), Step 5 (`interface_config` column).

---

## Scope

In-scope:

- `editor/tabs/assistant-interface-tab.component.ts/.html` — flesh out from placeholder:
  - **Header Display Heading Name** — text input, default "Your Brand Name 👋".
  - **Header Display Subheading Name** — text input, default "We're online and happy to assist you!".
  - **Initial Messages** — chip-list style; up to 2 chip-like bubbles editable inline; each with x button; "+ Add Message" button disabled when 2 present. Help text: "Enter each message in a new chat bubble. You can add only 2 initial messages."
  - **Display the "⚡ Powered by Pabbly" label** — select (Enable / Disable). *(Adapt to our brand — "Powered by CRM" per `feedback_branding_crm_not_furnicrm`; internal code identifier can keep `powered_by_label`.)*
    - Renaming rules: user-facing text says "Powered by CRM" (per memory `feedback_branding_crm_not_furnicrm`). Backend field name stays `powered_by_enabled` (no breaking rename).
  - **Footer Text** — text input default "Privacy Policy".
  - **Footer Link** — URL input default `https://www.example.com/privacy-policy/`.
  - Every field two-way binds to `form-state` under `interface_config.*` keys.
  - Preview pane immediately reflects changes.
- Types added to `form-state.service.ts` for `interface_config` shape.
- Preview component (`assistant-preview.component.ts` from Step 7) reads `interface_config` and renders: header rectangle with heading + subheading + close-x icon; initial-message bubbles; footer with powered-by (if enabled) + link.

Out of scope:
- Styling colours (Step 13).
- Real chat streaming (already wired in Step 9).
- Widget bundle (Step 15).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/assistant-interface-tab.component.ts` | **EDIT** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/assistant-interface-tab.component.html` | **EDIT** |
| `APP/src/app/features/user/core/ai-assistants/form-state.service.ts` | **EDIT** — extend types |
| `APP/src/app/features/user/core/ai-assistants/editor/preview/assistant-preview.component.ts` | **EDIT** — render interface_config |
| `APP/src/app/features/user/core/ai-assistants/editor/preview/assistant-preview.component.html` | **EDIT** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/assistant-interface-tab.component.spec.ts` | **NEW** |

**~6 files. ~250 lines.**

## Plan

1. Field-by-field forms with `ReactiveForms` + signal bridge (grep existing tab for form pattern).
2. Initial-message chips: each chip is a small editable input with x button; adding pushes to a signal array capped at 2.
3. Preview: uses safe interpolation for header text (no innerHTML). Renders default text when fields blank.
4. Powered-by label rendered as our "Powered by CRM" text per memory.
5. Prettier on all files.

## DB changes / migrations

None (`interface_config` JSONB already exists from Step 5).

## Tests

- Interface form saves and reloads all fields.
- Preview updates immediately on typing (test with fake timer + signal change detection).
- Cannot add 3rd initial message (button disabled).
- Powered-by toggle hides/shows label in preview.
- Footer link is safely rendered (no XSS if URL contains angle brackets).

## Smoke

```
1. Open Interface tab. Change header heading to "UrbanNest Realty".
   Preview updates instantly.
2. Add second initial message. "+Add" disabled after.
3. Toggle Powered-by off. Preview footer hides label.
4. Change footer link. Save. Reload. Persisted.
```

## Risks

- If Step 5 stored `interface_config` as JSONB with a specific shape, mismatched keys silently drop. Type-guard on read.

## Self-check (10 rules)

`APP/` only. ✓ N/A org_id. N/A rest. ✓ 6 files / ~250 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 12 — Assistant Interface tab UI
Files: 6
Verify: all fields save + reload; preview reflects live; initial-message cap enforced.
Tests: ~5 Angular component tests.
Awaiting "proceed".
```
