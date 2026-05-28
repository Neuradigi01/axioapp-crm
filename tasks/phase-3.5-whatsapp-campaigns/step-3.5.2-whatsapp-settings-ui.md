# Step 3.5.2 — Settings UI: WhatsApp Business Account card (connect/test/disconnect)

**Goal:** Angular card under `/user/settings/integrations` that wraps the Step-3.5.1 backend — paste-token connect form, live "Test connection" button, disconnect, and a status pill mirroring the Google/Meta cards' visual language.

**Phase:** 3.5 (WhatsApp Campaigns)
**Depends on:** 3.5.1 (backend: `/api/v1/integrations/whatsapp/*` endpoints)
**Status:** ✅ COMPLETED — commit 

After this step the Owner role can connect a WhatsApp Business Account via UI (no curl, no .env edit). Adapter rewire still pending → Step 3.5.3.

---

## Scope

### In-scope

- New `WhatsAppCardComponent` mirroring the structure of `MetaCardComponent`:
  - Header pill: 🟢 Connected / ⚪ Disconnected / 🔴 Error
  - When **disconnected**: shows a "Connect" CTA which expands a 5-field inline form
    - `phone_id` (text, required)
    - `waba_id` (text, required)
    - `access_token` (password-masked, required)
    - `app_secret` (password-masked, required)
    - `verify_token` (text, required, with helper text: "Choose any random string; you'll paste the same value into Meta's webhook console in Step 3.5.12")
    - `api_version` (text, default `v18.0`, collapsed under "Advanced")
    - Submit button: "Connect WhatsApp" → POST `/connect` → on 200 emit `changed` to parent so the list reloads
  - When **connected** OR **error**: shows the connected details:
    - `display_phone_number` and `verified_name` (large, prominent)
    - `phone_id`, `waba_id` (smaller, mono font — copyable)
    - "Test connection" button → POST `/test` → pill updates inline
    - "Disconnect" button → confirm dialog → POST `/disconnect` → emit `changed`
  - When **error**: red banner with `last_error` text, plus a "Reconnect" button that opens the same connect form
- Typed reactive forms (Angular 20+) with signals for state
- Inline error banner under the form on 400 response (Meta's error message verbatim)
- Loading states for all 3 buttons (Connect / Test / Disconnect)
- TailwindCSS for all styling (no PrimeNG, no Material) — same conventions as existing cards
- Service methods on `IntegrationsApiService`:
  - `getWhatsAppStatus()` → `WhatsAppStatus`
  - `connectWhatsApp(payload)` → `WhatsAppStatus`
  - `testWhatsApp()` → `WhatsAppStatus`
  - `disconnectWhatsApp()` → `void` (204)
- Type additions to the service:
  - Extend `IntegrationProvider` literal to include `'whatsapp'`
  - New `WhatsAppStatus` interface (matches backend `WhatsAppStatusOut`)
  - New `WhatsAppConnectPayload` interface (matches backend `WhatsAppConnectIn`)
- Wire into `integrations-page.component.{ts,html}`:
  - Add `<app-whatsapp-card>` after the Meta card
  - Re-use the page's existing `loadAll()` refresh on `(changed)` output

### Out-of-scope (deferred)

- **Adapter rewire** (env-var → DB lookup) — Step 3.5.3.
- **Template sync UI** — Step 3.5.4.
- **Campaign template picker** — Step 3.5.5.
- Permission gating in the sidebar (re-uses existing `settings.integrations.manage` — already gates the Settings → Integrations tab).
- E2E tests — out of scope per project convention (no e2e suite exists for the integrations tab).

---

## Files to touch

### Created (2)

- `APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.ts`
- `APP/src/app/features/user/core/settings/integrations/whatsapp-card.component.html`

### Modified (3)

- `APP/src/app/features/user/core/settings/integrations/integrations-api.service.ts` — extend `IntegrationProvider` literal + add 4 new methods + 2 new interfaces (~60 lines added)
- `APP/src/app/features/user/core/settings/integrations/integrations-page.component.ts` — load WA status alongside Google/Meta integrations (~10 lines added)
- `APP/src/app/features/user/core/settings/integrations/integrations-page.component.html` — render `<app-whatsapp-card>` (~5 lines)

**File budget:** 5 files. Well within ≤10 limit.

---

## Plan

1. **Extend service** — open `integrations-api.service.ts`:
   - Update `IntegrationProvider` type: `'google_ads' | 'meta_ads' | 'whatsapp'`
   - Add `WhatsAppStatus` + `WhatsAppConnectPayload` interfaces (mirror backend schemas exactly)
   - Add 4 methods: `getWhatsAppStatus()`, `connectWhatsApp()`, `testWhatsApp()`, `disconnectWhatsApp()` — all return Observables, all hit `/api/v1/integrations/whatsapp/*`
2. **Write the card** — `whatsapp-card.component.ts`:
   - Standalone, OnPush, signals-based state (`status`, `inlineError`, `formExpanded`, in-flight flags per button)
   - Typed reactive form `connectForm: FormGroup<...>` with the 5 required fields + 1 optional
   - `computed()` derivations: `isConnected`, `isError`, `pillClass`, `pillLabel`
   - Lifecycle: parent passes initial status via `input()`, card refetches on its own action completion
   - All HTTP calls use `takeUntilDestroyed(this.destroyRef)`
3. **Template** — `whatsapp-card.component.html`:
   - Header row: title + status pill (Tailwind colors matching meta-card's pill convention)
   - `@if (!isConnected())` → connect form panel
   - `@if (isConnected())` → connected details panel
   - `@if (inlineError())` → red banner
   - Test + Disconnect buttons in connected state, both with `aria-busy` while in-flight
4. **Wire into page** — `integrations-page.component.ts`:
   - Inject the new card via standalone imports
   - Add `whatsappStatus = signal<WhatsAppStatus | null>(null)` to page state
   - `loadAll()` already fan-outs to multiple APIs — add `getWhatsAppStatus()` to the parallel forkJoin
   - Pass status to card as input; subscribe to card's `(changed)` output → refetch
5. **Template wire** — `integrations-page.component.html`:
   - Render `<app-whatsapp-card [status]="whatsappStatus()" (changed)="loadAll()" />` after `<app-meta-card>`

---

## API contract (used by this component)

Already shipped in Step 3.5.1:

| Method | Endpoint | Body | Returns |
|---|---|---|---|
| `getWhatsAppStatus()` | `GET /api/v1/integrations/whatsapp/status` | — | `WhatsAppStatus` |
| `connectWhatsApp(payload)` | `POST /api/v1/integrations/whatsapp/connect` | `WhatsAppConnectPayload` | `WhatsAppStatus` (200) or `{detail: string}` (400) |
| `testWhatsApp()` | `POST /api/v1/integrations/whatsapp/test` | — | `WhatsAppStatus` (200) or `{detail: string}` (400) |
| `disconnectWhatsApp()` | `POST /api/v1/integrations/whatsapp/disconnect` | — | 204 (No Content) or `{detail: string}` (404) |

```typescript
// WhatsAppStatus mirrors backend WhatsAppStatusOut
interface WhatsAppStatus {
  status: 'connected' | 'disconnected' | 'expired' | 'error';
  phone_id?: string | null;
  waba_id?: string | null;
  display_phone_number?: string | null;
  verified_name?: string | null;
  api_version?: string | null;
  last_error?: string | null;
  connected_at?: string | null;
}

// WhatsAppConnectPayload mirrors backend WhatsAppConnectIn
interface WhatsAppConnectPayload {
  phone_id: string;
  waba_id: string;
  access_token: string;
  app_secret: string;
  verify_token: string;
  api_version?: string;
}
```

---

## Verification checklist (what you'll do after I finish)

**Build + lint:**
1. `cd APP && npm run build` → no TS/template errors.
2. `npm run lint` (if configured) → no new warnings.

**Visual smoke (browser, dev server):**
3. `cd APP && ng serve` (or `npm start`), login as Owner.
4. Go to `/user/settings/integrations` → see Google card, Meta card, and **WhatsApp card** in that order.
5. WhatsApp card shows ⚪ Disconnected pill with "Connect" CTA.
6. Click Connect → form expands with 5 fields + Advanced toggle.
7. Submit with bogus token → red banner shows "Meta API rejected the credentials: ...".
8. Submit with real test creds → form collapses, status flips to 🟢 Connected, displays `+91 …` and "Sharma Furniture".
9. Click "Test connection" → button shows spinner, returns 🟢.
10. Click "Disconnect" → confirm dialog → status flips to ⚪ Disconnected, sidecar (phone_id, waba_id) hidden.
11. Reconnect with same creds → re-encrypted, status 🟢 again.
12. **Mobile**: open at 360px viewport → card stacks vertically, form fields full-width, no overflow.
13. **Permission gate**: log in as a non-Owner role → the whole `/settings/integrations` route is already hidden by the sidebar; verify directly visiting the URL 403s on the API call (UI shows "permission denied" banner — already wired in the page).

**No regression:**
14. Google card connect / disconnect still works.
15. Meta card connect / disconnect still works.
16. DLQ list + status panel under the same page still load.

---

## Self-check against 10 rules

- [x] **Rule 1:** Frontend `features/user/core/` mein hi sab — no pack imports.
- [x] **Rule 2:** N/A (frontend, no tables).
- [x] **Rule 3:** Custom fields untouched.
- [x] **Rule 4:** Dynamic form rendering N/A (this is a fixed-5-field settings form, not an entity form).
- [x] **Rule 5:** Sidebar — already wired via existing `integrations` module; no new menu entry.
- [x] **Rule 6:** Permission registry — reuses `settings.integrations.manage`.
- [x] **Rule 7:** Pack manifest — N/A (core).
- [x] **Rule 8:** 5 files, ~600 lines across all. Within budget.
- [x] **Rule 9:** Stop & report at the end.
- [x] **Rule 10:** No TODOs / placeholders.

---

## Stop & report

After completing this step I will:
- List exact files changed with one-line each.
- Show `npm run build` clean output.
- Show 4 new API methods on the service + 2 new interfaces.
- Show the rendered card layout (3 states: disconnected / connected / error).
- **Await your "proceed" before Step 3.5.3 (adapter rewire: env-var → DB).**

---

## Pre-implementation question (one only)

**Q: Connect form mein "Test before save" button bhi rakhna hai?**

Do options:
- **(a) Single button "Connect WhatsApp"** — submit hits `/connect`, jo validate karke save karta hai. Single click, simple. (Like the backend already does — connect IS validate-then-save.)
- **(b) Two-step: "Test" then "Save"** — pehle ek "Test" button validate kare without saving, user confirm kare, fir "Save" se persist ho. Yeh extra step hai but operator ko comfort milta hai pehle test karne ka.

**Recommendation:** **(a)** — backend already validates before saving, aur error message clear hai. Two-step se UX redundant ho jata hai. Operator galti karega toh inline error mil jayega, retry kar sakte hain.

Aap batao **(a) ya (b)**, fir "begin" bolo → mai implement karta hoon.
