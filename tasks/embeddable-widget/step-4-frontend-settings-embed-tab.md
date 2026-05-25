# Step 4 — Frontend (Settings): Embed Integrations tab — keys + config + snippet

**Goal:** Add a new Settings tab `/user/settings/integrations/embed` where Owner/Admin can issue & revoke embed keys, edit the widget config (fields, button label, branding), and copy a ready-to-paste install snippet. Gated by `settings.integrations.embed.manage`.
**Track:** Embeddable Widget
**Status:** Done — `environment.embedWidgetHost` added (defaults to `http://localhost:5173` for dev; Step 5's Vite preview port). `EmbedApiService` wraps all 5 admin endpoints (listKeys/issueKey/revokeKey/getConfig/updateConfig). `IssueKeyModalComponent` ships a two-phase modal (form → reveal); the reveal phase shows the plaintext secret in a `<code>` block + Copy button (graceful fallback if Clipboard API fails on non-HTTPS), permanent warning banner, and "I've saved this key" checkbox that gates the Close button. `EmbedIntegrationsTabComponent` ships all 3 panels: (1) keys table with relative timestamps + status badges + per-row Revoke with confirm; (2) form-configuration with per-field label/placeholder/required + reorder up/down + interest options chip-input + submit-button label + thank-you message/URL + accent-color picker + logo URL + "Powered by" toggle, all wired through a single `dirty` signal that gates Save; (3) install snippet pre-filled with the most-recent live key prefix + Copy button. Tab registered in `settings-page.component.ts` TABS array with `permission: 'settings.integrations.embed.manage'` so it auto-hides for users without the key — Employees see no tab, Owners do. Dev build clean (18.7s, zero warnings). Notable adaptations: (a) the "drag to reorder fields" replaced with up/down buttons per spec's out-of-scope note; (b) snippet shows `<key-prefix>…` (e.g. `pk_live_AbC…`) since we never persist the plaintext — Owner pastes the full key from their saved-secret notes; (c) the existing tab-via-TABS-array pattern from standard-fields was reused instead of a separate route (which would have needed a Settings page tab registry that doesn't exist yet).
**Depends on:** Steps 1–3 (backend complete), Phase 1.5 (permissions + Settings page tab registry from the standard-field-overrides track).

---

## Scope

In-scope:

- New route `/user/settings/integrations/embed` registered with the Settings page tab registry.
- `EmbedIntegrationsTabComponent` with three panels:

  **Panel 1 — Keys**
  - Table of keys: name, prefix, created_at, last_used_at, status (Active/Revoked).
  - "Issue new key" button → modal:
    - Name input (optional).
    - On submit, POST → modal shows the full secret **once** with a "Copy" button and a permanent warning: "Save this somewhere safe — you won't be able to see it again."
  - Per-row revoke button (with confirm modal).

  **Panel 2 — Form configuration**
  - Field list (drag to reorder is **out of scope for v1**; an `Order ↑↓` button pair is sufficient).
  - Per-field row: label, placeholder, required toggle, hide toggle.
  - For `interest` field: editable options list (chip input).
  - Inputs: Submit button label, thank-you message, thank-you URL (optional URL with `https://…` validation).
  - Branding: accent colour picker (hex), logo URL (optional), "Show 'Powered by FurniCRM' link" toggle.
  - Save button → PUT /embed/config. Toast on success.

  **Panel 3 — Install snippet**
  - Shows the snippet with the most recently used (or selected) key pre-filled:
    ```html
    <div id="furnicrm-form"></div>
    <script src="https://widget.furnicrm.app/v1/widget.js" data-key="pk_live_…"></script>
    ```
  - "Copy" button. Below, a small "Test in a sandbox" link that opens `/user/settings/integrations/embed/preview` (a route that renders the actual widget bundle in an iframe for visual confirmation — Step 6 wires this).
  - If no key exists yet, show "Issue a key first" empty state.

- `embed-api.service.ts` — typed wrappers for all admin endpoints from Steps 1–3.

Out of scope:

- Drag-to-reorder fields (Order buttons are enough for v1).
- Multi-widget management.
- Submission log — Step 9.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/integrations/embed/embed-integrations-tab.component.ts` | created |
| `app/src/app/features/user/core/settings/integrations/embed/embed-integrations-tab.component.html` | created |
| `app/src/app/features/user/core/settings/integrations/embed/issue-key-modal.component.ts` | created |
| `app/src/app/features/user/core/settings/integrations/embed/issue-key-modal.component.html` | created |
| `app/src/app/features/user/core/settings/integrations/embed/embed-api.service.ts` | created |
| `app/src/app/features/user/core/settings/settings.routes.ts` | modified — register the route + tab |

**6 files.** Inside rule-8 budget.

## Plan

1. Generate `embed-api.service.ts` with `listKeys()`, `issueKey(name?)`, `revokeKey(id)`, `getConfig()`, `updateConfig(payload)`.
2. Build the three panels in `embed-integrations-tab.component.{ts,html}`. Use signals + computed throughout. Form state for Panel 2 is a `signal<WidgetConfig>(…)` initialised from the GET response.
3. Issue-key modal: shows the secret in a `<code>` block + Copy button (`navigator.clipboard.writeText`). Adds a banner: "This is the only time the key will be displayed."
4. Snippet panel: build the snippet string client-side. The widget host URL comes from an environment config (`environment.embedWidgetHost`, defaulting to `https://widget.furnicrm.app` in prod and `http://localhost:5173` in dev).
5. Register the tab in `settings.routes.ts`. Permission gate on the route guard.
6. Smoke per checklist.

## Tests

Manual smoke per checklist. No new unit tests.

## Smoke (browser)

```
1. Log in as Owner. /user/settings → side tab shows "Integrations → Embed widget".
2. Panel 1 is empty. Click "Issue new key". Name it "Main site". Submit.
   Modal shows secret once. Copy. Close.
3. Table now shows the key (Active, prefix visible, secret hidden).
4. Panel 2 loads the default config. Toggle "email" to hidden. Change submit
   button label to "Request a Quote". Set accent colour to #B45309. Save. Toast.
5. Reload the page. Changes persisted.
6. Panel 3 shows the install snippet with the new key pre-filled. Click Copy.
7. Click Revoke on the key row → confirm → status now "Revoked".
8. As Employee → tab is hidden from the Settings side nav. Direct URL → Access Denied.
```

## Risks

- **Settings page tab registry pattern:** confirm it's already in place from the standard-field-overrides track (Step 4 of that track introduced the tab registry). If a different pattern is in play, mirror it.
- **Clipboard API on non-HTTPS dev:** `navigator.clipboard.writeText` requires a secure context. On `http://localhost`, browsers usually allow it; in case they don't, fall back to a textarea + manual copy. Document fallback in the component.
- **Showing the secret only once UX:** users will close the modal before copying. Add a checkbox "I have saved this key" that must be ticked before the Close button enables.
- **Snippet host URL drift:** ensure `environment.embedWidgetHost` defaults to a sensible local dev value (Step 5 wires it).

## Rollback

Delete the new files. Revert the settings route registration. Backend state (keys, config) is unaffected.
