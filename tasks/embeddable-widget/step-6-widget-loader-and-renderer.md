# Step 6 — Widget: loader script + form renderer

**Goal:** Make the widget actually render the form. The loader auto-discovers its target div from a `<script data-key="…">` tag, fetches the org's config from `/api/v1/embed/config/public?key=…`, renders the fields as DOM nodes, captures UTM + referrer + landing URL, posts to `/api/v1/embed/leads` on submit, and shows the success state or per-field validation errors.
**Track:** Embeddable Widget
**Status:** Pending
**Depends on:** Steps 1–3 (backend), Step 5 (build pipeline).

---

## Scope

In-scope:

- Auto-init loader: when the script is loaded via `<script src="…/v1/widget.js" data-key="pk_…">`, the bundle reads the script tag's `data-key`, `data-mount` (optional, defaults to `furnicrm-form`), and `data-host` (optional, defaults to `https://api.furnicrm.app`) attributes, and auto-calls `init()`. No explicit `init()` call needed from the host page.
- `src/loader.ts` — handles the auto-init.
- `src/api.ts` — typed wrappers for `getConfig(key)` and `submitLead(key, payload)`. Uses native `fetch`. Handles 401/422/429 with specific error shapes.
- `src/renderer.ts` — builds the form's DOM tree from the config. Functions: `renderForm(mount, config, onSubmit)`, `renderSuccessState(mount, config)`, `renderError(mount, message)`.
- `src/attribution.ts` — `captureAttribution(): Attribution` — reads `document.referrer`, `window.location.href`, and parses UTM params from `URLSearchParams(window.location.search)`.
- `src/index.ts` rewritten to orchestrate:
  1. Read config from server.
  2. Render form.
  3. On submit: validate client-side (required, email format) → POST → success state or error.
- Fallback if config fetch fails: render the default fields (the same defaults documented in Step 3) so the form still works even if the config endpoint is briefly down.
- Per-field client-side validation: required, email format (`type="email"` is enough for v1), phone length sanity (≥ 7 digits after stripping non-digits).
- Loading state: form shows a spinner while config is being fetched.

Out of scope:

- No theming — Step 7 (renderer outputs semantic classes; styling comes next).
- No spam protection — Step 8 (renderer leaves a placeholder hidden honeypot field; the actual logic + min-time check lands in Step 8).
- No multi-step flow.
- No file inputs.
- No accessibility deep-dive beyond labels + required indicators + `aria-invalid` on error. Full a11y audit is a follow-on.

## Files to touch

| File | Action |
|---|---|
| `widget/src/index.ts` | rewritten — orchestrator |
| `widget/src/loader.ts` | created — auto-init from script tag |
| `widget/src/api.ts` | created |
| `widget/src/renderer.ts` | created |
| `widget/src/attribution.ts` | created |
| `widget/src/types.ts` | modified — add `Attribution`, `SubmissionPayload` types |
| `widget/dev/test-host.html` | modified — use the script-tag loader pattern (not the explicit-init pattern from Step 5) |
| `widget/test/renderer.test.ts` | created — jsdom unit tests for renderer + validation |

**8 files.** At rule-8 boundary. Renderer is the core artifact; splitting would scatter related logic.

## Plan

1. Build `attribution.ts`:
   ```ts
   export function captureAttribution(): Attribution {
     const params = new URLSearchParams(window.location.search);
     return {
       referrer: document.referrer || null,
       landing_url: window.location.href,
       utm_source: params.get("utm_source"),
       utm_medium: params.get("utm_medium"),
       utm_campaign: params.get("utm_campaign"),
       utm_content: params.get("utm_content"),
       utm_term: params.get("utm_term"),
     };
   }
   ```
2. Build `api.ts`:
   ```ts
   export async function getConfig(key: string, host: string): Promise<WidgetConfig> {
     const r = await fetch(`${host}/api/v1/embed/config/public?key=${encodeURIComponent(key)}`, { mode: "cors" });
     if (!r.ok) throw new ApiError(r.status, await r.text());
     return r.json();
   }
   export async function submitLead(key: string, host: string, payload: SubmissionPayload): Promise<SubmitResult> {
     const r = await fetch(`${host}/api/v1/embed/leads`, {
       method: "POST",
       mode: "cors",
       headers: { "Content-Type": "application/json", "X-FurniCRM-Key": key },
       body: JSON.stringify(payload),
     });
     const body = await r.json().catch(() => ({}));
     if (!r.ok) throw new ApiError(r.status, body.detail ?? "Submission failed");
     return body;
   }
   ```
3. Build `renderer.ts`:
   - For each `WidgetField` (sorted by `order`), build a `<div class="furnicrm-form__field">` containing `<label>` + the input (`<input>`, `<textarea>`, or `<select>`) with class `furnicrm-form__input`.
   - Submit button is `<button class="furnicrm-form__button">{label}</button>`.
   - On submit: prevent default, collect values via `FormData`, basic validation, callback.
   - Renders a hidden honeypot field `<input name="honeypot" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px;">` (Step 8 wires its meaning; here it's harmless).
4. Build `loader.ts`:
   ```ts
   function getScriptTag(): HTMLScriptElement | null {
     return document.currentScript as HTMLScriptElement | null
         ?? document.querySelector('script[src*="widget.js"]');
   }
   const script = getScriptTag();
   if (script) {
     const key = script.getAttribute("data-key");
     const mountId = script.getAttribute("data-mount") ?? "furnicrm-form";
     const host = script.getAttribute("data-host") ?? "https://api.furnicrm.app";
     if (key) init({ key, host, mountId });
   }
   ```
5. Rewrite `index.ts` to orchestrate:
   - Show spinner.
   - `getConfig` (fallback to default on error).
   - `renderForm(mount, config, async (payload) => { try { await submitLead(...); renderSuccessState(...); } catch (e) { renderError(...); } })`.
   - Track `rendered_at = new Date().toISOString()` at render time; include in submission payload.
   - Apply attribution: capture once at render time, include in every submission.
6. Update `dev/test-host.html`:
   ```html
   <script src="/v1/widget.js" data-key="pk_live_devplaceholder" data-host="http://localhost:8000"></script>
   ```
7. Tests with Vitest + jsdom — assert renderer outputs correct DOM, validation catches missing required, submit handler invokes the callback with the right payload shape.

## Tests

`widget/test/renderer.test.ts`:

- **Renders all fields:** given a 5-field config, the mount contains 5 input wrappers + 1 button.
- **Required validation:** submit empty form → button click does not trigger callback; required fields show `aria-invalid="true"`.
- **Submit happy path:** fill in fields → submit → callback invoked with `{full_name, phone, ...}` matching inputs.
- **Honeypot present:** rendered DOM contains the hidden honeypot input.
- **Success state:** after callback resolves, mount shows the thank-you message.
- **Error state:** if callback rejects, mount shows the error message (replacing or appearing above the form).

## Smoke

```powershell
cd widget
npm run build
npm run dev  # serves the bundle + dev/test-host.html

# In browser: http://localhost:5173/dev/test-host.html
# 1. Form renders with the default fields (config fetch likely succeeds against a running API
#    if a key was issued in the embed Step 1 smoke; otherwise falls back to defaults).
# 2. Submit empty form → required indicators show on empty required fields.
# 3. Fill in name + phone → submit → success message appears.
# 4. Check the CRM (running locally): /user/leads shows a new lead with source=Widget.
# 5. Open browser DevTools Network tab: confirm POST to /api/v1/embed/leads with X-FurniCRM-Key header.
# 6. Append ?utm_source=test&utm_campaign=spring to the test-host URL, reload, submit.
#    New lead's attribution JSONB contains those values.
```

## Risks

- **Cross-origin cookies / credentials:** the widget uses `mode: "cors"` without `credentials: "include"` — correct. The host's session cookies must not leak.
- **`document.currentScript` quirks:** works for non-async scripts. The install snippet does not use `async`/`defer`, so `currentScript` is reliable. Add a query-selector fallback for the edge case.
- **CSP on customer sites:** sites with strict CSP that disallows `connect-src` to `https://api.furnicrm.app` will fail. Document this in the README; customers must add the host to their CSP. Not solvable from our side.
- **Renderer XSS:** every value rendered (config labels, options) is set via `textContent` or `setAttribute`, never `innerHTML`. Lint rule or careful review on every renderer change.
- **Fallback config drift:** the embedded default config in the widget bundle could diverge from the backend's defaults. Keep them in sync by sourcing both from a shared JSON file at build time — or accept the drift and document that fallback fields are a frozen subset.

## Rollback

Revert the widget source files. Bundle build still works (returns to Step 5's placeholder). Backend untouched.
