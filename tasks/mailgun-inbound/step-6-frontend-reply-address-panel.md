# Step 6 — Frontend: Reply capture panel + capture toggle + warning banner

**Status:** COMPLETED — 2026-09-02. Reply capture sub-row live under each verified SMTP sender in Settings → Integrations → Email Sender (address pill + Copy + Capture toggle + amber warning banner when off); email attachments in the conversation thread render as downloadable links via the new `/api/v1/messages/{id}/attachments/{key}` endpoint. Full `ng build` clean.
**Effort:** ~0.5 day (actual: ~1.5 hours).
**Depends on:** Steps 1 + 2 (API exposes `inbound_reply_address` on sender detail; PATCH toggle endpoint exists).
**Blocks:** Nothing (Step 7 is Mailgun-side setup).

## Goal

On the SMTP sender card, add a "Reply capture" section showing the inbound reply address (`in_<token>@reply.neuradigi.com`), a Copy button, and a toggle for `capture_replies_in_crm`. When the toggle is off, show a warning banner explaining replies land at the SMTP mailbox, not the CRM.

Attachment download URL — the existing attachment renderer needs the new endpoint URL.

## Scope

**Files (verify paths in Step 6 exploration — repo lists `email-sender-card.component.ts` as the single combined list+detail component):**

- `app/src/app/features/user/core/settings/integrations/email-sender-card.component.ts`
- `app/src/app/features/user/core/settings/integrations/email-sender-card.component.html`
- `app/src/app/features/user/core/settings/integrations/email-senders.service.ts` (parse new response field, PATCH toggle)
- `app/src/app/features/user/core/settings/integrations/models.ts` — `InboundReplyAddress` type

**Component additions:**

- New section in the card: "Reply capture" — reveal only if `sender.inbound_reply_address` is present in the response.
- Renders the address as a monospace pill with a Copy button (reuse existing copy-button component; if none, use `navigator.clipboard.writeText`).
- Toggle (existing Tailwind toggle pattern): "Capture replies in CRM" — bound to `capture_replies_in_crm`.
- When toggle=OFF: standard amber warning banner (per memory `feedback_standard_warning_banner_pattern.md` — `border-amber-500/20 bg-amber-500/10 text-amber-400 rounded-md p-3` — do NOT reinvent) with text: "Replies will go to your SMTP inbox instead of the CRM. Turn on to capture replies here."

**Service:**

- `email-senders.service.ts` — extend the sender detail response type; new `setCaptureToggle(senderId, capture: boolean)` method calling `PATCH /api/v1/settings/email-senders/{id}/capture-toggle`.
- Existing HTTP retry interceptor applies automatically (memory `feedback_http_retry_interceptor.md`).

**Attachment renderer:**

- Grep for the existing conversation attachment renderer component. Change the download URL constructor to `/api/v1/messages/{message_id}/attachments/{storage_key}` (new endpoint from Step 5). If the existing renderer uses a different provider-specific URL for WhatsApp, keep those unchanged — only add the email-attachment path.

**Prettier:**

- Run `npx --no-install prettier --write` on all touched files before commit (memory `feedback_prettier_on_write.md`).

**Lucide icons:**

- If any new icons introduced (e.g., `copy`, `info`), verify they're registered in `app.config.ts` (memory `feedback_lucide_icon_registry.md`).

## Tests

Karma:

- `test_sender_card_renders_reply_address_with_copy_button` — verify element exists when API returns `inbound_reply_address`.
- `test_sender_card_hides_reply_section_when_address_absent` — old API shape (no field) → section not rendered.
- `test_sender_card_copy_button_writes_to_clipboard` — click, assert `navigator.clipboard.writeText` called.
- `test_sender_card_capture_toggle_shows_warning_banner_when_false` — toggle off, banner visible with amber classes.
- `test_sender_card_capture_toggle_hides_warning_banner_when_true` — toggle on, banner absent.
- `test_sender_card_toggle_calls_patch_endpoint` — click, assert HTTP PATCH fired with correct payload.

## Self-check

- [ ] Component path verified against actual repo (not assumed).
- [ ] Amber warning banner uses the standard classes; no gradients / shadows / custom tooltips (memory rule).
- [ ] Copy button uses existing pattern if one exists — grep before creating new component.
- [ ] Prettier run before commit.
- [ ] Lucide icons registered.
- [ ] Response type is optional — component doesn't crash if API returns null `inbound_reply_address` (defensive during phased deploy).
- [ ] No hardcoded domain names in the frontend — the address comes from the API, never constructed client-side.

## Report template

```
Files changed: <list>
Prettier ran on: <list>
Lucide icons added: <if any>

Manual verify (staging):
  1. Go to Settings → Integrations → SMTP Senders. Pick a verified sender.
  2. See "Reply capture" section with `in_<token>@sandbox<hex>.mailgun.org`.
  3. Click Copy — clipboard has the address.
  4. Toggle off — amber banner appears. Toggle back on — banner gone.
  5. Refresh page — toggle state persisted.

Tests: 6 Karma.

Self-check: all pass.

Awaiting proceed for Step 7.
```
