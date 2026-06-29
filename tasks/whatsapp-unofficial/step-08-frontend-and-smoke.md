# Step 8 — Frontend connect card + QR pairing modal + end-to-end smoke

**Goal:** Land the operator-facing surface and close the track. Add a "WhatsApp Web (Unofficial)" card on Settings → Integrations alongside the existing Cloud card. Pair flow: click Connect → modal opens → SSE stream pushes the QR data URL → operator scans → modal closes on connection.opened. Banner on the inbox flags Web conversations as "Unofficial — at risk." End-to-end smoke confirms every flow: pair, send text, send media, react, receive, internal note, tag, opt-in toggle, block, disconnect, reconnect-after-restart.
**Track:** WhatsApp Unofficial (Baileys)
**Status:** Pending
**Depends on:** Step 7 (channel adapter wired so sends work).

---

## Scope

In-scope:

- **`whatsapp-web-card.component.ts`** — Settings → Integrations panel addition:
  - Empty (disconnected) state: title "WhatsApp Web (Unofficial)", subtitle "Pair with QR. Free, but at-risk — use Cloud API for transactional sends.", primary button "Connect WhatsApp Web".
  - Click → opens the QR modal.
  - Connected state: paired phone number, "Connected on Jun 29, 2026" timestamp, "Disconnect" button (confirms with a dialog).
  - Error state: red banner with `last_error`, Retry button.
  - Polls `GET /api/v1/integrations/whatsapp-web/status` once per minute as a fallback when no SSE is active (cheap; 60 req / hour per operator-on-this-page).
- **`whatsapp-web-qr-modal.component.ts`** — pairing modal:
  - Opens with a loading spinner.
  - On open: calls `POST /connect`. On 200, opens an `EventSource` to `/qr-stream`.
  - Renders the live QR data URL as `<img>`. QR rotates every ~20s — modal updates seamlessly on each `qr.updated` event.
  - Two-step instructions: "1. Open WhatsApp → Settings → Linked Devices. 2. Tap 'Link a device' and scan."
  - On `connection.opened` event: modal flips to success state ("Connected as +91 9876543210") → auto-closes after 2s.
  - On `connection.logged_out` / sidecar error: shows the error inline with Retry.
  - Cancel button: calls `POST /disconnect` and closes.
  - The modal does NOT poll. SSE is the only source of truth during pairing.
- **Banner on Web conversations** — chat-thread header gets a small amber pill:
  - Renders only when `Conversation.provider === 'whatsapp_web'` (new computed field on `ConversationOut` — backed by a lookup against the active `Integration` row for the conversation's channel).
  - Text: "Unofficial WhatsApp Web — sends can be blocked / number can be banned."
  - Tooltip on hover with link to docs.
  - Same component reused on the conversations-list-page row so operators see the flag in the inbox list too.
- **TypeScript service** — `whatsapp-web.service.ts`:
  - Typed API client for `connect / disconnect / status`.
  - `qrStream(): Observable<QrEvent>` — wraps `EventSource` in an Observable, auto-cleans on unsubscribe.
- **`ConversationOut.provider` field exposure** — backend addition:
  - The conversations list / detail endpoints already join `Integration` for the active org; add a `provider: 'whatsapp' | 'whatsapp_web' | null` field. Computed once at query time (not per row — the org has at most 2 active providers).
  - Updates the existing `Conversation` TypeScript interface.
- **Compose / interactive UI gating**:
  - Existing button / list / CTA builder modal on the conversation thread hides itself when the conversation's provider is `whatsapp_web`. Replaces with a small inline note: "Interactive messages require WhatsApp Cloud."
  - The Send-As-Template picker (Step 9 of the upgrade track) hides similarly.
- **End-to-end smoke checklist** (this step's deliverable, not a code file):
  - Document below 12 scenarios. Each must pass before this step is reported done.
- **Tests**:
  - `whatsapp-web.service.spec.ts` — service unit tests (3 cases: connect, status, observable cleanup).
  - `whatsapp-web-card.component.spec.ts` — 4 cases (disconnected → connected → error states, click behaviour).
  - `whatsapp-web-qr-modal.component.spec.ts` — 3 cases (SSE message → QR render, connected → close, cancel → disconnect).
  - No new backend tests. The handful of small backend additions in this step (provider field exposure) are covered by extending existing conversation tests.

Out of scope:

- **Permission registration UI** — reuses existing `settings.integrations.manage` already wired.
- **Documentation site / customer-facing docs** — separate track.
- **Multi-Web-number** — future track.
- **A separate ban-recovery flow** — for v1, if Web disconnects with `loggedOut`, the operator re-clicks Connect → re-scans. Banner explains.
- **Sidecar deployment automation** — Dockerfile is there, but `docker-compose.yml` integration / k8s manifests are outside the per-step budget.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/settings/integrations/whatsapp-web-card.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/integrations/whatsapp-web-card.component.html` | **NEW** |
| `APP/src/app/features/user/core/settings/integrations/whatsapp-web-qr-modal.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/integrations/whatsapp-web-qr-modal.component.html` | **NEW** |
| `APP/src/app/features/user/core/settings/integrations/integrations.page.html` | **MODIFY** — mount the new card next to the Cloud card |
| `APP/src/app/features/user/core/conversations/services/whatsapp-web.service.ts` | **NEW** |
| `APP/src/app/features/user/core/conversations/components/unofficial-banner.component.ts` | **NEW** |
| `APP/src/app/features/user/core/conversations/components/chat-thread.component.html` | **MODIFY** — render banner; hide interactive / template builders on Web |
| `APP/src/app/features/user/core/conversations/components/conversation-list-row.component.html` | **MODIFY** — render mini banner |
| `APP/src/app/features/user/core/conversations/models/conversation.model.ts` | **MODIFY** — add `provider` field |
| `API/src/app/core/conversations/schemas.py` | **MODIFY** — add `provider` to `ConversationOut` |
| `API/src/app/core/conversations/service.py` | **MODIFY** — populate `provider` in detail / list response (single join already in place) |
| `APP/src/app/features/user/core/settings/integrations/__tests__/...` | **NEW** — 3 spec files |
| `tasks/whatsapp-unofficial/README.md` | **MODIFY** — flip all step statuses to Done |

**14 files. ~500 lines net.** At rule-8 ceiling — accept since 4 of them are tests + 2 are small HTML mounts.

## Plan

1. **Backend provider exposure first** — add `provider` to `ConversationOut`, write the join in `conversations/service.py`. One test case in the existing conversations test file.
2. **`whatsapp-web.service.ts`** — typed client with `connect()`, `disconnect()`, `status()`, `qrStream()`.
3. **`whatsapp-web-card.component.ts`** — signal-driven, mirrors the existing Cloud `whatsapp-card.component.ts` shape (read existing for visual + permission conventions).
4. **`whatsapp-web-qr-modal.component.ts`** — opens, subscribes to SSE, displays QR, handles success / error / cancel.
5. **`unofficial-banner.component.ts`** — small standalone component, two variants (full / mini).
6. **Wire into chat-thread.component.html + conversation-list-row.component.html** — show banner only when `conversation.provider === 'whatsapp_web'`.
7. **Hide interactive / template builders on Web** — `*ngIf` / `@if` against the provider field.
8. **Specs** — 10 cases total across 3 spec files.

## DB changes / migrations

**None.** Schema is complete. The `provider` field on the response is a computed join.

## Tests

- **Backend:** 1 case added to `test_conversations_service.py` asserting `provider` field is populated.
- **Frontend specs:** 10 new cases.

## End-to-end smoke checklist (this is the step's deliverable)

Each scenario must be **manually verified once on a developer machine with a real phone**. Tick boxes go in the Step 8 report.

```
SETUP
- [ ] Sidecar built + started (npm run build && npm run start).
- [ ] FastAPI migrated to head, started.
- [ ] Frontend running (npm start, ng serve, or docker-helper).
- [ ] Test org has no Cloud + no Web connected yet.

PAIRING
- [ ] Visit Settings → Integrations. "WhatsApp Web (Unofficial)" card
      renders with Connect button.
- [ ] Click Connect. Modal opens. Loading → QR appears within ~3s.
- [ ] QR rotates (replaces) at least once during the pairing window.
- [ ] Scan with personal phone. Modal flips to success + closes in ~2s.
- [ ] Card now shows the paired number + Disconnect button.

INBOUND
- [ ] From phone, send "smoke test 1" to the paired number.
- [ ] Conversations inbox shows the new conversation within 2s
      (channel=whatsapp, with "Unofficial" amber banner).
- [ ] Send image from phone → image bubble appears with thumbnail.
- [ ] Send location from phone → location bubble (existing component
      from Step 28 of upgrade track) renders correctly.
- [ ] Send reaction (long-press + 👍) → reaction lands on the original
      message bubble.

OUTBOUND
- [ ] Reply with text → phone receives within 2s. Status double-tick
      arrives within 5s.
- [ ] Send image → phone receives.
- [ ] Send location (composer location dialog from Step 28) → phone
      receives.
- [ ] React with ❤️ → phone sees the reaction.
- [ ] Try sending an interactive button message via the existing
      builder → composer rejects with the documented inline note.
- [ ] Try Send-As-Template → picker hidden.

EXISTING FEATURES STILL WORK
- [ ] Add an internal note → renders yellow, phone NEVER receives.
- [ ] Add a tag → chip renders on row + thread.
- [ ] Block the contact from chat-thread header → next inbound from
      the same number is dropped server-side (no new message row).
- [ ] Toggle opt-out manually → re-send → composer/send refuses with
      the existing "opted out" error.

RECONNECTION
- [ ] Restart sidecar (kill + re-run). Within 30s the Settings card
      still shows connected; manager.restoreAll re-paired the session.
- [ ] Send a message → still works.

DISCONNECT
- [ ] Click Disconnect → confirms dialog → card flips to disconnected.
- [ ] Sidecar log: session destroyed.
- [ ] storage/sessions/<org_id>/<session_id>/ folder removed.

NEGATIVE PATHS
- [ ] Kill sidecar entirely. Click Connect → 502 with "sidecar
      unavailable" message in the modal. Modal cancellable.
- [ ] Connect Cloud API on the same org (existing flow). Both providers
      can coexist on different numbers; existing Cloud conversations
      keep using Cloud, Web conversations use Web (verified by sending
      a test message on each).
- [ ] Try to create a campaign when only Web is connected → 400 with
      the documented "Campaigns require Cloud" message.
```

## Risks

- **SSE reconnect.** If the operator's browser disconnects mid-pairing, the EventSource auto-reconnects (browser default). The QR may have rotated by then — frontend handles this by always rendering whatever the most-recent event delivered.
- **Modal stuck open.** If `connect.opened` is missed (network blip), the 1-min polling fallback resolves it. Modal also has a "Cancel" button.
- **Provider field on conversation list performance.** The added join is a single LEFT JOIN against `Integration` — same join already runs in the inbox query. Costs nothing extra.
- **Banner copy.** The "at-risk" framing is honest but might worry customers. Marketing review the copy before ship — captured as a follow-up review note in the Step 8 report.
- **Sidecar deployment surface.** Production deploy needs a process supervisor (docker-compose / systemd / pm2). Out of step scope but documented in `sidecars/whatsapp-web/README.md` so the deploy track has the recipe.

## Self-check (10 rules)

- [ ] Rule 1: No core ↔ packs.
- [ ] Rule 2: No schema changes.
- [ ] Rule 3–7: N/A. Settings → Integrations card is added as a child component, not a new sidebar/menu/permission/pack-yaml entry.
- [ ] Rule 8: 14 files, ~500 lines.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. Banner copy is final. Polling fallback is real (60s).

## Stop & report

```
Step 8 — Frontend connect card + QR pairing modal + end-to-end smoke

Files changed:
- 7 new frontend files (card, modal, service, banner, 3 specs)
- 5 modified frontend (integrations page mount, chat-thread, list row,
  conversation model, conversations service spec)
- 2 modified backend (conversations schemas.py + service.py)

What you can verify:
- The full 12-scenario E2E smoke checklist above is green
- The Settings → Integrations page renders both Cloud and Web cards
  side-by-side
- QR pairing modal completes end-to-end with a real WhatsApp number
- Conversation inbox flags Web conversations with the "Unofficial"
  banner
- All upgrade-track features (notes, tags, opt-in, block, location
  send/receive, reactions) work on Web conversations
- Cloud vs Web coexist on the same org without interference
- Campaigns explicitly refuse Web-only orgs
- Frontend specs: 10 new cases green; existing specs unchanged
- README.md status table: all 8 steps marked Done

Self-check: 10 rules, all green.

Track complete. Open follow-ups (deferred to separate small tracks
if/when needed):
- Multi-Web-number per org
- Sidecar Postgres-backed session storage (interface already in place)
- Ban-recovery flow + persistent rate-limit tuning
- Multi-replica sidecar (Redis pub/sub)

Awaiting your "proceed".
```
