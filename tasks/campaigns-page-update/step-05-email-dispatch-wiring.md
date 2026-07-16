# Step 05 — Wire Email dispatch through `adapter.send_email()` + funnel columns + tracking

**Goal:** Email campaigns actually send. Dispatch branches on channel — Email calls `adapter.send_email(account_id, subject, body_html, body_text, ...)` instead of the broken generic `adapter.send()`. Per-message rows flip through `queued → sent → delivered → opened → clicked / bounced` as tracking data flows back from the existing Gmail/Microsoft sync path.
**Track:** Campaigns page update — Email
**Status:** Pending
**Depends on:** Step 03 (sender identity + subject), Step 04 (body_html)

Screen references in [`preview.html`](preview.html):

- **Screen 5 · Campaign Detail — Email running** — funnel with Sent / Delivered / Opened(pixel) / Clicked / Bounced boxes + recipient table with per-status timestamp columns + Retry-failed action.

---

## Scope

Backend only. This step is the actual "Email campaigns work" step.

- Extend `CampaignMessage` with tracking timestamp columns.
- Branch `dispatch_chunk` on channel. WA path unchanged. Email path resolves the mailbox + template/inline body, substitutes merge tags, calls `adapter.send_email()`, records the message id returned.
- Extend the campaign stats aggregator to compute Email-specific rates (open rate, click rate, bounce rate).
- Wire Email tracking callbacks — the existing Gmail/Microsoft sync pipeline hits `apply_email_status()` on the campaigns service (new function) parallel to the existing `apply_meta_status()`.

**Explicitly NOT in this step:**

- Unsubscribe token in the footer (Step 06).
- Pre-flight bounce suppression / sender-readiness enforcement (Step 07).

## Schema

Migration `00XX_campaign_message_email_tracking.py`:

| Column on `tbl_campaign_messages` | Type | Constraint | Why |
|---|---|---|---|
| `opened_at` | TIMESTAMPTZ | nullable | First pixel hit. Set-once (idempotent — later hits are no-op). |
| `first_click_at` | TIMESTAMPTZ | nullable | First tracked link click. |
| `bounced_at` | TIMESTAMPTZ | nullable | Set when bounce classifier flips the row to failed with reason `hard_bounce` / `soft_bounce`. |
| `bounce_type` | TEXT | nullable | `hard` / `soft` / `spam_complaint` — from `EmailBounce.bounce_type`. |
| `unsubscribed_at` | TIMESTAMPTZ | nullable | Set when the contact unsubscribed via the campaign footer link (Step 06 populates it — column lands now to avoid a second migration). |

Existing enum on `CampaignMessage.status` extends with two states if not already present: `opened`, `clicked`. Check the current enum — if `sent → delivered → read → failed` is the current shape, add `opened` + `clicked` as forward-only states after `delivered`. Migration handles the enum extension.

## Backend — dispatch branch

### `campaigns/service.py::dispatch_chunk`

Today ([`campaigns/service.py`](../../api/src/app/core/campaigns/service.py) around line 479–795) all channels flow through:

```python
adapter.send_template(...)   # WA branch
adapter.send(...)            # everything else — raises for Email
```

Rewrite the per-contact block as a channel branch:

```python
if campaign.channel == ConversationChannel.whatsapp:
    external_id, provider_status = adapter.send_template(
        to=contact.phone,
        template_name=template.name,
        language=template.language,
        variables=resolved_variables,
        header_type=template.header_type,
        header_text=template.header_text,
    )
elif campaign.channel == ConversationChannel.email:
    external_id, provider_status = adapter.send_email(
        account_id=campaign.email_account_id,
        to=contact.email,
        sender_name=campaign.sender_name,
        reply_to=campaign.reply_to or account.email_address,
        subject=render_subject(campaign.subject, contact),
        body_html=render_body(effective_body_html, contact),
        body_text=render_body(effective_body_text, contact),
        preheader=campaign.preheader,
        campaign_id=campaign.id,
        campaign_message_id=cm_row.id,
    )
else:
    raise NotImplementedError(f"Channel {campaign.channel} is not supported")
```

`effective_body_html` and `effective_body_text` — from `campaign.template.body_html/_text` if `template_id` set, else from `campaign.body_html/_text` (Step 04's inline compose).

`render_subject` / `render_body` — small utility that substitutes `{{first_name}}` etc from the contact record. Extend the existing WA variable-binding utility to handle merge tags (they're both curly-brace substitutions). One shared helper in `campaigns/utils.py`.

The Email adapter (`core/conversations/adapters/email.py`) already:

- Injects the tracking pixel into `body_html` for open tracking.
- Rewrites links to route through the tracking gateway for click tracking.
- Injects the CAN-SPAM footer.
- Accepts `campaign_id` + `campaign_message_id` for callback lookup — verify these are already threaded through; if not, extend the adapter signature.

If a call raises `EmailAccountDisconnectedError` / `EmailQuotaExceeded` / any Meta-side equivalent, the row is marked failed with the classified reason. Same pattern as the existing WA error branch.

### `campaigns/service.py::apply_email_status`

New function parallel to `apply_meta_status`:

```python
def apply_email_status(
    db: Session,
    org_id: UUID,
    external_message_id: str,
    status: str,  # 'delivered' | 'opened' | 'clicked' | 'bounced'
    timestamp: datetime,
    bounce_type: str | None = None,
) -> None:
    ...
```

- Forward-only state machine (delivered can't go back to sent).
- Set the corresponding timestamp column, idempotent (only set if null).
- For `bounced`, set `bounced_at` + `bounce_type` and mark row failed.
- Idempotent — the same webhook / sync event can arrive twice, second call is no-op.

### Existing Gmail/Microsoft sync integration

The existing email sync path (already delivering read receipts + bounce records into `tbl_email_bounce` etc) — extend the classifier to also look up whether the message is tied to a `CampaignMessage` (via a stored `external_message_id` header or the `campaign_message_id` we passed to `send_email()`). When it is, call `apply_email_status()`.

Where the existing sync lives: check `core/email/` and `core/conversations/adapters/email.py` for the message-ingest / bounce-classifier path. Reuse; do not fork.

### Stats aggregator

`campaigns/service.py::get_campaign_stats` — extend to include:

- `opened` count + `open_rate = opened / delivered`
- `clicked` count + `click_rate = clicked / delivered`
- `bounced` count + `bounce_rate = bounced / sent`

WA campaigns get zeros in these columns (open pixel doesn't apply — WA has `read` instead).

## Frontend

### Campaign detail page

- Extend the stats row to render Sent / Delivered / **Opened** / **Clicked** / **Bounced** boxes when `campaign.channel === 'email'`. WA campaigns keep the existing Sent / Delivered / Read (with the existing violet accent) plus a Replied box.
- Recipient table — add columns for the Email-specific timestamps (Opened, First-click). Table already scrolls horizontally when there are many columns.
- Retry-failed action already exists per-message — no change.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_campaign_message_email_tracking.py` | created |
| `api/src/app/core/campaigns/models.py` | modified — new tracking columns + enum extension |
| `api/src/app/core/campaigns/schemas.py` | modified — stats response schema extended with `opened`, `clicked`, `bounced`, `bounce_rate` |
| `api/src/app/core/campaigns/service.py` | modified — channel-branched dispatch + `apply_email_status` |
| `api/src/app/core/campaigns/data_access.py` | modified — helper to find `CampaignMessage` by external id (bulk-mark by status) |
| `api/src/app/core/campaigns/utils.py` | created or modified — shared `render_subject` / `render_body` merge-tag substitutor |
| `api/src/app/core/conversations/adapters/email.py` | modified only if `campaign_id` / `campaign_message_id` aren't already threaded through (verify first) |
| `api/src/app/core/email/bounce_handler.py` (or wherever bounce classifier lives) | modified — call `apply_email_status` when message ties back to a campaign |
| `api/tests/test_email_campaign_end_to_end.py` | created |
| `app/src/app/features/user/core/campaigns/campaign-detail.page.ts` | modified — Email-specific columns |
| `app/src/app/features/user/core/campaigns/campaign-detail.page.html` | modified — Email funnel rendering |

**~10 files + 1 migration.** At the edge — split into `05a` (dispatch wiring) + `05b` (frontend funnel + stats) if line count exceeds ~400.

## Tests

`test_email_campaign_end_to_end.py`:

- **Happy path:** Draft Email campaign (from Step 03/04) → start → dispatch called with mocked `send_email()` → row moves from queued → sent, external_message_id stored.
- **Provider error:** `send_email()` raises `EmailAccountDisconnectedError` → row moves to failed with reason `account_disconnected`. Rest of the chunk continues.
- **Delivered webhook:** call `apply_email_status(status='delivered')` → row flips to delivered, `delivered_at` set. Second call is no-op.
- **Opened:** call `apply_email_status(status='opened')` → row flips to opened, `opened_at` set. Idempotent second call.
- **Clicked:** call `apply_email_status(status='clicked')` → row flips to clicked, `first_click_at` set. Idempotent.
- **Bounced:** call `apply_email_status(status='bounced', bounce_type='hard')` → row flips to failed, `bounced_at` + `bounce_type` set.
- **Merge tag substitution:** subject `"Hi {{first_name}}"` + contact with `first_name='Aditi'` → adapter receives `"Hi Aditi"`. Empty `first_name` → falls back to "Customer" (matching existing WA behaviour in `service.py` line 906–932).
- **Stats aggregator:** all five counts + rates surface correctly.
- **WA unaffected:** WA campaign end-to-end (existing test) still passes.

## Verification

Ajay's Workspace:

1. Draft an Email campaign via the wizard (Step 03/04 fields filled), audience = 3 contacts including your own email.
2. Start. Within a few seconds the CampaignMessage rows flip from queued → sent. Check via psql `SELECT status FROM tbl_campaign_messages WHERE campaign_id = '...'`.
3. Check your inbox. The email arrives with the correct subject, HTML body rendered, merge tags resolved.
4. Open the email in your inbox → within ~10 sec the row flips to `opened` in the campaign detail page (funnel Opened count = 1).
5. Click a link in the email → row flips to `clicked` (funnel Clicked count = 1).
6. Send another campaign to a known hard-bounce address (e.g. `nobody@nonexistent-domain-12345.example`) → row flips to failed with reason `hard_bounce` after the sync ingests the bounce.
7. Detail page renders Sent / Delivered / Opened / Clicked / Bounced boxes correctly, with the recipient table columns showing timestamps.
8. Rerun a WA campaign — funnel still shows Sent / Delivered / Read / Replied (no regression).

## Self-check (fill in before the stop-and-report)

- 10 rules: line-by-line
- Layered architecture: `service.py` is the only file calling `db.commit()`; `apply_email_status` uses DAL for the row update, `render_*` utils are pure functions in `utils.py`
- Reuse: existing Email adapter, existing bounce classifier, existing merge-tag substitution logic (extended to a shared helper)
- Query efficiency: dispatch already chunks; new lookup for `CampaignMessage` by external id uses a covering index on `external_message_id` — add it in the migration if missing
- Tooling: prettier + eslint + ruff on all touched files; migration verified up + down inside docker helper

## Awaiting your `proceed`

Done means: real Email campaigns send, funnel populates, opens/clicks/bounces track back correctly, WA regression clear, pytest suite green, browser smoke green. **Ship gate: Email happy path works after this step.**
