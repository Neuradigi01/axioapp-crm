# Step 3 — Embedded Signup frontend popup flow

**Goal:** Replace the existing 5-field manual paste form on the WhatsApp integration card with a single "Connect WhatsApp" button that opens Meta's Embedded Signup popup. Customer logs into Facebook (if needed), selects/creates their WABA + phone number, completes setup inside Meta's popup, and the popup posts back a `code` + `phone_number_id` + `waba_id` which our frontend ships to the Step-2 backend endpoint. **End user never types a token, ID, or app secret.** Old 5-field form preserved behind an "Advanced (self-host)" collapsible for on-prem customers without Meta partner access.
**Track:** WhatsApp Platform Upgrade — Phase 1 (Embedded Signup)
**Status:** Pending
**Depends on:** Step 1 (Meta App config + ES Configuration ID), Step 2 (backend exchange endpoint).

---

## Scope

In-scope:

- **Refactor [`whatsapp-card.component.ts`](APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.ts):**
  - **Primary CTA:** Single big "Connect WhatsApp" button (blue, with WhatsApp logo).
  - **Secondary collapsible:** "Advanced — paste credentials manually" link below the button → expands to the existing 5-field form (current default surface). Hidden by default; for on-prem / self-host customers.
  - **Connected state:** if integration is already connected, show a "Connected" card with: business name (`verified_name`), display phone (`+91 80XXX XXXXX`), WABA ID (truncated), connected date, **Disconnect** button, **Send test message** button. Phone health strip (quality + tier badges) deferred to Phase 4 — leave a placeholder div.
  - **Loading states:** button shows spinner while popup is open; disable form fields during exchange call; toast notifications for success / failure.
- **Load Facebook JS SDK on demand** (only when user clicks Connect):
  - Inject `<script async defer src="https://connect.facebook.net/en_US/sdk.js">` if not already loaded.
  - On load, call `FB.init({ appId, xfbml: false, version: 'v19.0' })` with `appId` pulled from a new public-safe config endpoint (`GET /api/v1/integrations/whatsapp/embedded-signup/config`) returning `{ app_id, config_id, graph_api_version }`.
  - Window-level `fbAsyncInit` handler — standard Meta pattern.
- **Trigger Embedded Signup:**
  ```ts
  FB.login(
    (response) => {
      if (response.authResponse) {
        this.completeExchange(response.authResponse.code, this.signupSessionInfo);
      } else {
        this.toast.error('Connection cancelled');
      }
    },
    {
      config_id: '<CONFIG_ID from backend>',
      response_type: 'code',
      override_default_response_type: true,
      extras: { feature: 'whatsapp_embedded_signup', sessionInfoVersion: 3 },
    }
  );
  ```
- **Listen for postMessage from facebook.com origin:**
  - `window.addEventListener('message', (event) => { ... })` filtering by `event.origin === 'https://www.facebook.com'`.
  - Capture session info payload: `event.data.event === 'FINISH' && event.data.data` contains `phone_number_id` + `waba_id`. Store in component state until `FB.login` callback fires.
- **Complete exchange:**
  - POST `{ code, phone_number_id, waba_id }` to `/api/v1/integrations/whatsapp/embedded-signup/exchange`.
  - On 200: refresh status from existing `GET /api/v1/integrations/whatsapp/status` and re-render in "Connected" state.
  - On 4xx/5xx: show error toast with the backend's user-facing message.
- **New backend endpoint** `GET /api/v1/integrations/whatsapp/embedded-signup/config`:
  - Returns `{ app_id, config_id, graph_api_version }` — sourced from env settings.
  - No auth gating beyond `require_authenticated` (no secrets in response — `app_id` and `config_id` are public-safe values designed to be in frontend JS).
- **Telemetry events** (frontend → existing analytics service):
  - `whatsapp.embedded_signup.button_clicked`
  - `whatsapp.embedded_signup.sdk_loaded`
  - `whatsapp.embedded_signup.popup_opened`
  - `whatsapp.embedded_signup.popup_completed`
  - `whatsapp.embedded_signup.popup_cancelled`
  - `whatsapp.embedded_signup.exchange_succeeded`
  - `whatsapp.embedded_signup.exchange_failed` (with error code)
- **Accessibility:**
  - Connect button has `aria-label="Connect WhatsApp via Meta Embedded Signup"`.
  - Popup-cancelled state announced to screen readers via existing toast system.
- **i18n:** All new strings sourced from existing i18n keys file (English-only initially per project convention).

Out of scope:

- **Phone health strip** (quality / tier badges). Phase 4 wires this — placeholder div only.
- **Send test message functionality.** Existing test ping wiring stays as-is; new modal UI for "send test message" is Phase 2 (when outbound media is built).
- **Multi-number selection UI.** Step 2 picks first phone number; frontend just displays which one was selected and includes the "N more numbers available — multi-number support coming Phase 9" note.
- **WhatsApp Business Profile editor.** Separate sub-page in Phase 4.
- **Permission gate refactor.** Continues to use existing `settings.integrations.manage`.

## Files to touch

| File | Action |
|---|---|
| [`APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.ts`](APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.ts) | Major rewrite of disconnected-state view; Connected state expanded; new ES button + popup logic |
| [`APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.html`](APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.html) | New layout: hero Connect button + collapsible Advanced + Connected state card |
| `APP/src/app/features/user/core/settings/integrations/whatsapp-fb-sdk.service.ts` | **NEW** — encapsulates FB SDK loading + `FB.login` + postMessage listener lifecycle |
| [`APP/src/app/features/user/core/settings/integrations/integrations.service.ts`](APP/src/app/features/user/core/settings/integrations/integrations.service.ts) | Add `getEmbeddedSignupConfig()` + `exchangeEmbeddedSignup(payload)` methods |
| [`API/src/app/core/integrations/whatsapp/router.py`](API/src/app/core/integrations/whatsapp/router.py) | Add `GET /embedded-signup/config` route (returns public app_id + config_id) |
| [`APP/src/app/features/user/core/settings/integrations/integrations.types.ts`](APP/src/app/features/user/core/settings/integrations/integrations.types.ts) | TypeScript types: `EmbeddedSignupConfig`, `EmbeddedSignupExchangeRequest/Response`, `WhatsAppConnectedState` |
| `APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.spec.ts` | **NEW** — Jest tests covering: button renders, SDK loads on click, popup callback wires correctly, Connected state renders post-exchange |

**~7 files (5 modified + 2 new). ~450 lines total — at upper edge of rule-8 budget. Acceptable because the component refactor is one cohesive surface.**

## Plan

1. **Read the current [`whatsapp-card.component.ts`](APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.ts) end-to-end.** Note: 5-field form structure, validation, save flow, Connected state, Test/Disconnect buttons.
2. **Backend config endpoint** in `router.py`:
   ```python
   @router.get("/embedded-signup/config", response_model=EmbeddedSignupConfigResponse)
   async def embedded_signup_config(_: User = Depends(get_current_user)):
       return EmbeddedSignupConfigResponse(
           app_id=settings.integrations.meta_app_id,
           config_id=settings.integrations.whatsapp_embedded_signup_config_id,
           graph_api_version=settings.integrations.whatsapp_graph_api_version,
       )
   ```
3. **Frontend service** `whatsapp-fb-sdk.service.ts`:
   ```ts
   @Injectable({ providedIn: 'root' })
   export class WhatsAppFbSdkService {
     private sdkLoaded = signal(false);
     private postMessageHandler?: (event: MessageEvent) => void;

     async loadSdk(appId: string, version: string): Promise<void> { ... }
     async openSignup(configId: string): Promise<{ code: string; phoneNumberId: string; wabaId: string }> {
       // wires FB.login + postMessage listener, returns promise that resolves on FINISH
       // rejects on cancel / popup_closed_by_user
     }
     private listenForSessionInfo(): Promise<{ phoneNumberId: string; wabaId: string }> { ... }
   }
   ```
4. **Component rewrite** `whatsapp-card.component.ts`:
   - Inject `WhatsAppFbSdkService` + `IntegrationsService`.
   - Signal-based state: `connectionState: 'disconnected' | 'connecting' | 'connected'`, `error: string | null`.
   - `onConnectClick()` method orchestrates: load SDK → open popup → exchange → refresh status.
   - Existing 5-field form moved into a `<details>` collapsible.
5. **Template** `whatsapp-card.component.html`:
   ```html
   @if (connectionState() === 'disconnected') {
     <div class="connect-hero">
       <button (click)="onConnectClick()" class="btn-primary">
         <img src="/assets/icons/whatsapp.svg" alt="" />
         Connect WhatsApp
       </button>
       <p class="text-xs text-zinc-500">
         You'll be redirected to Meta to authorize Core CRM and pick
         your WhatsApp Business number. Takes about 2 minutes.
       </p>
       <details class="mt-4">
         <summary>Advanced — paste credentials manually</summary>
         <!-- existing 5-field form -->
       </details>
     </div>
   } @else if (connectionState() === 'connecting') {
     <div class="spinner-block">...</div>
   } @else {
     <div class="connected-card">
       <h3>{{ connectedState().verifiedName }}</h3>
       <p>{{ connectedState().displayPhoneNumber }}</p>
       <p class="text-xs text-zinc-500">Connected {{ connectedState().connectedAt | date }}</p>
       <button (click)="onDisconnect()">Disconnect</button>
       <button (click)="onTestMessage()">Send test message</button>
     </div>
   }
   ```
6. **Tests** in `.spec.ts`:
   - Disconnected → Connected after successful exchange.
   - Connect button shows spinner during exchange.
   - Cancelled popup → error toast, returns to disconnected.
   - Advanced collapsible expands and existing form is functional.
   - Exchange error from backend renders human-readable message.
7. **No `.env.example` change** beyond Step 1's additions — frontend reads config from API, not from env.

## DB changes / migrations

**None.** Frontend-only refactor + backend GET endpoint that reads from settings.

## Tests

- Frontend: `whatsapp-card.component.spec.ts` (Jest, ~6 cases).
- Backend: extend `test_whatsapp_embedded_signup.py` (from Step 2) with a `GET /embedded-signup/config` case — assert it returns the configured values and respects auth.

## Smoke

After dev server rebuilds:

```
1. Log in as Owner of Ajay's Workspace (per smoke-test-target-org memory).
   Navigate to /user/integrations.

2. Locate the WhatsApp card. Expected: NEW UI — a single "Connect
   WhatsApp" hero button + collapsible "Advanced — paste credentials
   manually" link. Old 5-field form NOT visible by default.

3. Click "Advanced" → confirm the 5-field form expands and is functional.
   Collapse it again.

4. Click "Connect WhatsApp" hero button. Expected:
   - Button shows spinner.
   - Facebook popup window opens at facebook.com/v19.0/dialog/oauth?...
   - Popup shows "Connect your account to Core CRM" branding (per Step 1
     dashboard config).

5. In the popup, complete the flow with the Neuradigi test WhatsApp
   Business number:
   - Select "Use existing number" path (virtual-number / display-name
     option is hidden per Step 1's ES Configuration).
   - Pick the verified business number.
   - Authorize the requested permissions.
   - Popup closes automatically.

6. Card transitions to "Connected" state showing:
   - Verified name (e.g. "Neuradigi Technologies")
   - Display phone (e.g. "+91 80XXX XXXXX")
   - Connected date
   - Disconnect + Send test message buttons

7. Verify DB:
     SELECT phone_id, waba_id, display_phone_number, verified_name
     FROM tbl_whatsapp_account_configs
     WHERE org_id = '41f9ede9-41b3-44ce-b489-3004566d4068';

8. Click "Send test message" — confirms existing test ping still works
   on the new connection.

9. Click "Disconnect" → card returns to disconnected state.

10. Re-run the connect flow with a wrong-account login → confirm
    Step-2's idempotency upsert handles re-connection cleanly (single
    row, updated values).

11. Cancel the popup mid-flow → confirm error toast appears + card stays
    in disconnected state. No DB rows created.

12. Trigger a backend error path (e.g. revoke webhook subscription
    permission mid-flow) → confirm friendly error message renders
    instead of raw 5xx.

13. Log in as Sales-Junior (no settings.integrations.manage):
    - Integrations sidebar entry hidden.
    - Direct URL /user/integrations → access-denied (existing behavior).

14. Mobile/responsive: open in browser dev tools at iPad width. Popup
    UX is Meta-controlled; our card must render correctly. Confirm.
```

## Risks

- **Meta App Review not yet passed.** Until `whatsapp_business_management` permission is approved, only added testers can complete ES. Demoer must be added as a Tester (Step 1's checklist). For real customers, Step 4 → submit App Review → wait 1-3 weeks before flipping ES default-on for all orgs.
- **HTTPS required.** Meta blocks `http://` in ES popup. Local dev needs ngrok / Cloudflare Tunnel. Document the dev-setup gotcha in the smoke section.
- **FB JS SDK adds ~80KB to first-paint on integrations page.** Mitigation: lazy-load only on Connect click, not on page mount.
- **postMessage origin spoofing.** Strict origin check (`event.origin === 'https://www.facebook.com'`) prevents malicious iframes injecting fake session info. Already in plan; just don't forget.
- **Popup blocker.** Browser popup blockers can prevent `FB.login` from opening. If detected (FB SDK returns null status), show a tooltip: "Your browser blocked the connection popup. Allow popups for app.core-crm.com and try again."
- **Stale `connectionState` on tab return.** If user opens the popup, switches tabs, returns later, the state may be stale. Use `visibilitychange` to re-check status on return.
- **Advanced form regression.** Refactoring the surrounding component must not break the existing manual-paste path. Test case included.

## Self-check (10 rules)

- [ ] Rule 1: All in `app/core/settings/integrations/` + `app/core/integrations/whatsapp/`. No `packs/` imports.
- [ ] Rule 2: No DB changes.
- [ ] Rule 3: Custom fields engine untouched.
- [ ] Rule 4: Form is part of the integration setup surface, not a custom-field-driven entity. Acceptable per existing pattern (other integrations use static forms here too).
- [ ] Rule 5: Module registry untouched.
- [ ] Rule 6: Reuses existing `settings.integrations.manage` permission.
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: 7 files, ~450 lines (upper edge of budget — single cohesive surface).
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: Manual-form fallback preserved (explicit alternate path, not commented-out / dead code).

## Stop & report

```
Step 3 — Embedded Signup frontend popup flow

Files changed:
- APP/.../whatsapp-card.component.ts — Connect button + popup orchestration
- APP/.../whatsapp-card.component.html — new disconnected/connecting/connected layout
- APP/.../whatsapp-fb-sdk.service.ts — NEW FB SDK lifecycle service
- APP/.../integrations.service.ts — getEmbeddedSignupConfig + exchangeEmbeddedSignup
- APP/.../integrations.types.ts — new TS types
- API/.../whatsapp/router.py — GET /embedded-signup/config endpoint
- APP/.../whatsapp-card.component.spec.ts — NEW tests

What you can verify:
- /user/integrations → WhatsApp card shows hero Connect button
  (no 5-field form by default)
- Advanced collapsible expands the legacy form
- Click Connect → FB popup opens with Core CRM branding
- Complete popup with test number → card flips to Connected state
- DB shows ES-connected org's row populated (verified_name, etc.)
- Disconnect button + Send test message both functional
- Permission gate unchanged (Sales-Junior sees nothing)
- Cancelled popup → clean error toast, no orphan rows

Tests added:
- 6 Jest specs in whatsapp-card.component.spec.ts
- 1 pytest case for GET /embedded-signup/config (auth + value check)

Self-check: 10 rules, all green.

End-to-end ES flow now works for testers added in Meta App
Dashboard. Real customer rollout still blocked on Step 4's
data-deletion callback + Meta App Review submission.

Next: Step 4 — data deletion callback endpoint required by Meta App
Review for whatsapp_business_management permission approval.

Awaiting your "proceed".
```
