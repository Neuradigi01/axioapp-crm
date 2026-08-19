# Step 15 — Widget extension (form-or-chat) + snippet modal

**Goal:** Extend the existing `widget/` bundle to render an AI-chat interface when the embed key's `resource_type='ai_assistant'`. SSE via `fetch()` + `ReadableStream` (embed key stays in Authorization header, never URL). DOMPurify-sanitised markdown. localStorage session token for end-user identity. Copy-paste snippet modal in the editor.
**Status:** COMPLETED
**Depends on:** Step 14 (public router + embed keys), Step 13 (styling + interface configs available for widget consumption).

---

## Scope

In-scope:

- Extend `widget/` bundle (existing lead-capture widget at repo root):
  - `widget/src/loader.ts` — on init, fetch `/api/v1/public/ai-assistants/assistant` with the embed key; if response indicates `resource_type='ai_assistant'`, load the chat renderer; else keep the existing form renderer.
  - `widget/src/chat.ts` — **NEW** — the AI chat widget:
    - Bootstraps a chat window using the `styling_config` and `interface_config` from `GET /assistant`.
    - Session token: read from `localStorage.getItem('crm_ai_session_' + embed_key_prefix)`; if missing, call `POST /session/init` and store the returned token.
    - CAPTCHA: on first message, render Turnstile widget; include token in `POST /message`.
    - Streaming: use `fetch(url, { headers: { Authorization: 'Bearer ' + key } })` returning `ReadableStream`; decode SSE `data:` lines and append tokens to the current assistant bubble.
    - Markdown rendering: `marked` (small) + `DOMPurify` sanitiser. No raw HTML pass-through.
    - Retry: transient network errors (net::ERR_NETWORK_CHANGED per memory `feedback_http_retry_interceptor`) retry once with backoff.
    - Idle-close: if the user hasn't messaged for 30 min, allow the widget to display "Chat again?" prompt (no auto-close of the widget itself).
  - `widget/src/renderer.ts` — dispatch to `form.ts` or `chat.ts` based on resolved resource type.
  - `widget/src/styles.ts` — extend to consume the 8 colour tokens from `styling_config`.
  - `widget/src/spam.ts` — reused for AI chat (rate-limit is server-side but client-side pre-check helps).
  - `widget/src/api.ts` — extend with `/session/init`, `/message`, `/assistant` endpoints.
- `widget/package.json` — add `marked`, `dompurify` deps if not present.
- `widget/README.md` — document the two modes (form vs chat) and the `resource_type` dispatch.
- `widget/dist/` — rebuild output; committed per existing widget convention.
- **Snippet modal** in the editor:
  - `editor/embed/embed-snippet-modal.component.ts/.html` — invoked from the editor header **Embed** button (activated in this step).
  - Shows an issued embed key (creates one on first open if none exist), a **Copy Snippet** button, and the snippet:
    ```html
    <div id="crm-ai-assistant" data-key="{key}"></div>
    <script src="https://{host}/widget/loader.js" defer></script>
    ```
  - Domain allow-list editor (comma-separated) with Save.
  - "Rotate key" and "Revoke immediately" buttons wired to Step 14 endpoints.
- Frontend API client (`ai-assistants-api.service.ts`) — add embed-key methods.

Out of scope:
- Analytics / conversation history (Step 16).
- Retention (Step 17).

## Files to touch

| File | Action |
|---|---|
| `widget/src/chat.ts` | **NEW** |
| `widget/src/loader.ts` | **EDIT** — resource_type dispatch |
| `widget/src/renderer.ts` | **EDIT** |
| `widget/src/styles.ts` | **EDIT** — apply styling_config tokens |
| `widget/src/api.ts` | **EDIT** — 3 new endpoints |
| `widget/package.json` | **EDIT** — marked, dompurify |
| `widget/README.md` | **EDIT** — document chat mode |
| `widget/dist/loader.js` | **EDIT** — rebuilt output |
| `APP/src/app/features/user/core/ai-assistants/editor/embed/embed-snippet-modal.component.ts` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/embed/embed-snippet-modal.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/ai-assistant-editor.page.ts` | **EDIT** — enable Embed button |
| `APP/src/app/features/user/core/ai-assistants/ai-assistants-api.service.ts` | **EDIT** — embed-key endpoints |
| `widget/tests/chat.test.ts` | **NEW** |
| `widget/tests/loader-dispatch.test.ts` | **NEW** |

**~14 files. ~600 lines.** Widget bundle rebuild + editor modal + tests.

## Plan

1. Review existing `widget/src/` layout to match module conventions.
2. `chat.ts` is the biggest new file — extract sub-modules (`stream.ts` for the fetch-SSE reader; `render.ts` for DOM construction) if it grows over 250 lines.
3. Markdown: `marked` with `breaks: true`, `gfm: true`; then `DOMPurify.sanitize()` with default config.
4. SSE reader: `response.body.getReader()` + `TextDecoder`; parse `data: ` lines; treat `data: [DONE]` as terminator.
5. Session token: `localStorage` keyed by embed-key-prefix (first 8 chars) so different assistants on the same domain don't collide.
6. Snippet modal loads existing keys via `GET /ai-assistants/{id}/embed-keys`; if empty, prompts operator to create one first.
7. Widget bundle build uses existing vite config; `npm run build` in `widget/` produces `dist/`.
8. Prettier on Angular files.

## DB changes / migrations

None.

## Tests

Widget:
- Loader with a form-resource key renders form (no regression).
- Loader with ai_assistant-resource key renders chat.
- Chat sends `POST /message` with Authorization header (never URL query).
- SSE tokens append to bubble in order.
- CAPTCHA rendered on first message; not on subsequent.
- Session token persists across reload.
- Retry on 502 with exponential backoff.
- DOMPurify strips `<script>` from LLM output.

Frontend snippet modal:
- Modal shows snippet with a real embed key.
- Copy button copies to clipboard.
- Rotate button calls rotate endpoint.
- Revoke button calls revoke endpoint + refreshes.

## Smoke

```
1. Deploy widget bundle to a local HTTP server on port 8080.
2. Create simple HTML page: <div id="crm-ai-assistant" data-key="emb_xxx"></div>
   <script src="http://localhost:8080/loader.js"></script>
3. Load page. Chat widget appears with configured styling.
4. Type "Hello". See streamed tokens.
5. Reload page. Session persists (localStorage). Chat history intact.
6. From editor, click Embed → Rotate key → copy new snippet → old key still works
   for 7 days (if grace) or dies immediately (default).
```

## Risks

- Vite build must be reproducible; run in CI and diff `dist/` output.
- DOMPurify config: default is safe but strict; test with real markdown outputs to ensure code blocks and links render.
- Turnstile client-side widget: needs siteverify key in prod; dev bypass works locally.

## Self-check (10 rules)

`widget/` + `APP/` frontend. ✓ N/A org_id (resolved at API). N/A rest. ✓ 14 files / ~600 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 15 — Widget extension (form-or-chat) + snippet modal
Files: 14
Verify: widget renders both modes by resource_type; SSE via fetch/ReadableStream;
        embed key in Authorization header; DOMPurify strips scripts; snippet modal
        copy/rotate/revoke work end-to-end.
Tests: ~12 widget + Angular tests.
Awaiting "proceed".
```
