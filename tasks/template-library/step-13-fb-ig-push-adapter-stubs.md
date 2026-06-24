# Step 13 — Facebook / Instagram / Push sub-forms and stub adapters

**Goal:** Add Facebook Messenger, Instagram Direct, and Push notification as template channels in the editor. Stub adapters registered (no transport). These channels have NO external template-approval pipeline (Meta dropped FB Messenger message templates post-2020; IG Direct never had them; push is internal-only). Internal review workflow applies as normal.
**Status:** Pending
**Depends on:** Step 12 (SMS pattern). Steps 1-8.

---

## Scope

In-scope:
- `core/conversations/adapters/facebook.py` — `FacebookAdapter` stub: `send()` raises `FacebookNotConfigured`, `parse_webhook()` raises `NotImplementedError`. Registered for `ConversationChannel.facebook`.
- `core/conversations/adapters/instagram.py` — `InstagramAdapter` stub: same pattern. Registered for `ConversationChannel.instagram`.
- `core/conversations/adapters/push.py` — `PushAdapter` stub: same pattern. Registered for `ConversationChannel.push` (new enum value — add to migration).
- `ConversationChannel` enum gets `push` added if not already present. Confirm against `models.py:44-50` — `whatsapp / instagram / facebook / sms / email` exist; add `push` only.
- Migration `<ts>_add_push_channel_enum.py` — `ALTER TYPE conversation_channel ADD VALUE 'push'`.
- Frontend sub-forms:
  - `APP/.../core/templates/editor/fb-form.component.{ts,html}` — used for **both** Facebook Messenger AND Instagram Direct (channels render identical fields; Meta uses the same Messaging API for both).
    - Body text (1000 char, Messenger limit).
    - Quick replies (up to 13, 20 chars each — Messenger spec).
    - Variable picker support.
  - `APP/.../core/templates/editor/push-form.component.{ts,html}` — push notification.
    - Title (50 char).
    - Body (240 char).
    - Action URL / deeplink (optional).
- Editor page wires FB sub-form when `channel in (facebook, instagram)`; push sub-form when `channel=push`.
- List page + channel chip + status badge: add chips for FB Messenger, IG Direct, Push.

Out of scope:
- Actual FB Messenger / IG Direct integration (Meta Messaging API OAuth + conversation surface — that's a future channel-adapter track).
- Push provider integration (Firebase Cloud Messaging / OneSignal / APNS).
- Inbound FB/IG/push webhooks.
- External approval workflow — none exists for these channels; `external_status` stays `n_a`.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_add_push_channel_enum.py` | **NEW** — ALTER TYPE |
| `API/src/app/core/conversations/models.py` | edit — add `push` to ConversationChannel |
| `API/src/app/core/conversations/adapters/facebook.py` | **NEW** — stub |
| `API/src/app/core/conversations/adapters/instagram.py` | **NEW** — stub |
| `API/src/app/core/conversations/adapters/push.py` | **NEW** — stub |
| `APP/src/app/features/user/core/templates/editor/fb-form.component.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/fb-form.component.html` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/push-form.component.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/push-form.component.html` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/template-editor.page.ts` | edit — wire FB / IG / push sub-forms |
| `API/tests/templates/test_channel_stubs.py` | **NEW** |

**~11 files. ~450 lines** — at Rule 8's upper bound; each new file is small (most ~30-50 lines).

## Plan

1. Enum migration — `ALTER TYPE conversation_channel ADD VALUE 'push'`. SA 2.x + PG handle this directly.
2. Three stub adapters with consistent error messages.
3. Editor sub-forms — `fb-form` reused for FB Messenger AND Instagram Direct; `push-form` separate.
4. Editor channel-switch logic: `case 'facebook': case 'instagram': mount fb-form; case 'push': mount push-form;`.
5. Channel chips on list page + filter dropdown include the new channels.
6. Tests: all three stubs registered + raise the right exceptions.

## DB changes / migrations

One enum extension migration.

## Tests

5 pytest cases:
- `FacebookAdapter` registered + `send()` raises.
- `InstagramAdapter` registered + `send()` raises.
- `PushAdapter` registered + `send()` raises.
- `parse_webhook()` raises `NotImplementedError` for all three.
- `ConversationChannel.push` value exists after migration.

## Smoke

```
1. /user/templates/new → channel=Facebook Messenger → fb-form mounts with body + quick replies.
2. Save Draft → row appears in /user/templates list with Facebook chip.
3. Switch channel=Instagram Direct → same form, IG chip in list.
4. Switch channel=Push → push-form mounts with title + body + URL.
5. Try test send for FB → response is the configured stub error message ("Facebook Messenger transport not yet enabled; this is template-library only").
```

## Risks

- ALTER TYPE on a live enum can require special care; in PG 17 it's straightforward and non-blocking when adding a value at the end.
- Reusing fb-form for both FB and IG — they're structurally identical at this stage; if Meta later diverges them, split. Documented as acceptable v1.

## Self-check (10 rules)

`core/templates/` + `core/conversations/adapters/`. ✓ org_id N/A on stubs. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Sidebar already registered. Permissions: `templates.read/write` cover all channels. pack.yaml untouched. ✓ 11 files / ~450 lines — at limit; per-file ~30-50 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 13 — FB / IG / push sub-forms and stub adapters
Files: 11
Verify: FB / IG / push channels usable in editor; templates persist; stub adapters cleanly refuse send with informative error.
Tests: 5 pytest cases.
Awaiting "proceed".
```
