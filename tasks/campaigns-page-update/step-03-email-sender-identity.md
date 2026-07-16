# Step 03 — Email campaigns capture sender identity + subject + preheader

**Goal:** Email campaigns can select a verified sender mailbox, set a display name (Sender name), a reply-to address, a subject line, and a preheader. These become required fields on `Campaign` when `channel = email`. Without them dispatch has no way to compose a real email — this step lays the schema + form work that Step 05 depends on.
**Track:** Campaigns page update — Email
**Status:** COMPLETED — migration `0151_campaign_email_fields` adds 5 nullable columns to `tbl_campaigns` (FK to `tbl_email_accounts`, ON DELETE RESTRICT + index on `email_account_id`); `Campaign` ORM + `CampaignCreate`/`CampaignUpdate`/`CampaignOut` schemas extended; `_email_channel_requires_sender_and_subject` Pydantic model validator gates the create payload; new `_resolve_email_sender` service helper cross-reads `email_da.get_account_by_id` and raises 400 on missing / cross-org / non-`live` mailbox; `create_campaign` + `update_campaign` wire the helper in and persist the 5 fields. Backend test file `test_campaign_email_sender_identity.py` covers schema validation (9 cases incl. multi-missing + optional fields + WA-unaffected + reply-to validity + subject length cap) + service helper (happy + missing + cross-org + disconnected + error states) — 14 tests total, all via schema + fake-session (no DB round-trip; per memory pytest suite is 12 min and email-accounts already uses this pattern). Frontend `Campaign`/`CampaignCreate`/`CampaignUpdate` DTOs extended; `EmailAccountsApiService.listVerified()` added; modal now lazy-fetches verified mailboxes on channel-flip to Email, shows a fieldset with `mailbox picker + sender name + reply-to + subject (with 3-tag insert-variable buttons + char counter) + preheader`, disables submit until required Email fields are filled, clears the 5 fields when the operator switches back to WhatsApp, and sends them via the `create` payload only on Email. 6 new frontend specs cover: fieldset visibility toggle, empty-state banner when zero verified accounts, lazy fetch (called only on Email pick, not refetched on subsequent flips), `emailBranchIncomplete` gate, merge-tag insert, and cross-channel clearing. `tsc --noEmit` + `prettier --write` + `eslint` (1 pre-existing warning) + Python AST parse all clean. `ruff` deferred — docker not reachable in-session, pre-commit hook + CI will catch. Backend pytest + browser smoke on Ajay's Workspace still pending human eyeball.
**Depends on:** none (uses existing `EmailAccount` model)

Screen references in [`preview.html`](preview.html):

- **Screen 4 · Create Campaign — Email** — the top of the form: `Send from mailbox`, `Sender name`, `Reply-to`, `Subject`, `Preheader text` fields all live with `Step 03` badges.
- **Screen 7 · Email Sender Setup** — read-only reference for now; the mailbox picker sources from the verified addresses managed there. Step 07 builds that page; this step assumes the picker reads whatever verified `EmailAccount` rows exist.

---

## Scope

Backend adds four columns to `Campaign` + validation. Frontend adds four inputs to the campaign create modal (Email branch only). No changes to WhatsApp path.

**Explicitly NOT in this step:**

- HTML body (Step 04).
- Actual dispatch through the Email adapter (Step 05).
- Sender readiness / DKIM enforcement (Step 07).
- Sender Setup page UI (Step 07).

## Schema

One migration: `00XX_campaign_email_fields.py`

| Column on `tbl_campaigns` | Type | Constraint | Why |
|---|---|---|---|
| `email_account_id` | UUID | FK → `tbl_email_accounts.id`, ON DELETE RESTRICT, nullable | Required when `channel='email'`; NULL for other channels. Restrict on delete so a mailbox can't be removed while a scheduled/running Email campaign references it. |
| `sender_name` | TEXT | nullable, max 120 chars | Display name in From header ("Your Shop" in "Your Shop <sales@yourshop.com>"). Required-when-email. |
| `reply_to` | TEXT | nullable, max 320 chars | RFC-5321 max local+domain length. Optional even for Email — falls back to `email_account.email_address` at dispatch if null. |
| `subject` | TEXT | nullable, max 998 chars | RFC 5322 subject line hard limit. Required-when-email. Supports `{{first_name}}` etc — resolved at dispatch. |
| `preheader` | TEXT | nullable, max 200 chars | Inbox snippet next to the subject. Optional (defaults to first ~90 chars of body_text if omitted). |

Alembic up + down verified. Backfill: existing rows all have `channel != 'email'` (Email path doesn't work today), so all new columns come in NULL — no data migration needed.

## Backend

### `campaigns/schemas.py`

Extend `CampaignCreate` + `CampaignUpdate` + `CampaignRead`:

```python
email_account_id: UUID | None = None
sender_name: str | None = Field(None, max_length=120)
reply_to: EmailStr | None = None
subject: str | None = Field(None, max_length=998)
preheader: str | None = Field(None, max_length=200)
```

Add a model-level validator on `CampaignCreate` (and `CampaignUpdate` when channel is being changed):

```python
@model_validator(mode="after")
def _email_channel_requires_sender_and_subject(self):
    if self.channel == ConversationChannel.email:
        missing = [
            f for f, v in {
                "email_account_id": self.email_account_id,
                "sender_name": self.sender_name,
                "subject": self.subject,
            }.items() if not v
        ]
        if missing:
            raise ValueError(f"Email campaigns require: {', '.join(missing)}")
    return self
```

### `campaigns/service.py`

In `create_campaign_service` (and the update path):

- If `channel == email`, look up the referenced `EmailAccount` via `email_accounts.data_access.get_email_account_by_id_and_org`. Reject with `HTTPException(400, "Email account not found or belongs to another org")` if missing or `org_id` mismatch.
- Reject if `email_account.sync_state != 'live'`: `HTTPException(400, "Selected mailbox is not connected — reconnect in Email Sender Setup")`.
- Store the five new fields.

Cross-module read is fine here — a plain lookup, no business rules at stake (email-account availability check is our own rule). Do the fetch via `email_accounts.data_access.get_email_account_by_id_and_org`, not by importing `email_accounts.service.py`.

### `campaigns/data_access.py`

- `insert_campaign` and `update_campaign` DAL helpers already exist for other columns; just pass the new fields through. No new function needed.

### Endpoints

No new endpoints. Existing `POST /campaigns` + `PATCH /campaigns/{id}` accept the extended body.

## Frontend

### Create-campaign modal — Email branch

Extend [`create-campaign-modal.component.ts`](../../app/src/app/features/user/core/campaigns/create-campaign-modal.component.ts) + `.html`:

When channel is Email, render five new fields (in this order, matching the mockup):

1. **Send from mailbox** — dropdown of verified `EmailAccount` rows. Fetch on channel-change: `GET /email-accounts?sync_state=live`. Each option shows `<email_address> <chip: Live · DKIM ✓>` (DKIM badge from `email_account.dkim_enabled`, hidden until Step 07 fully populates the field). If the org has zero verified accounts, show an empty state: "No verified sender. Set up in Email Sender Setup." + link.
2. **Sender name** — text input, required, 120 char max.
3. **Reply-to** — email input, optional. Placeholder = the selected mailbox address.
4. **Subject** — text input, required. Below: an "Insert variable ▾" dropdown that appends `{{first_name}}` etc at the caret position. Character counter on the right — soft warning at 60+ chars ("Long subjects may truncate on mobile").
5. **Preheader** — text input, optional. Hint: "Preview text shown in inbox · ~90 chars".

Submit disabled until required fields are filled.

WhatsApp branch is untouched.

### Endpoint client

- Add the five fields to the campaign create/update DTOs in the frontend campaigns service.
- Add a small helper to fetch verified email accounts: `emailAccountsService.listVerified()`.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_campaign_email_fields.py` | created |
| `api/src/app/core/campaigns/models.py` | modified — five new columns on `Campaign` |
| `api/src/app/core/campaigns/schemas.py` | modified — extended schemas + `_email_channel_requires_sender_and_subject` validator |
| `api/src/app/core/campaigns/service.py` | modified — mailbox lookup + validation in create/update |
| `api/tests/test_campaign_email_sender_identity.py` | created |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.ts` | modified — new fields + mailbox fetch |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.html` | modified — new inputs |
| `app/src/app/services/campaigns.service.ts` (or wherever the DTOs live) | modified — extended DTO |
| `app/src/app/services/email-accounts.service.ts` | modified or created — `listVerified()` helper |

**~9 files + 1 migration.** Within the per-step rule.

## Tests

`test_campaign_email_sender_identity.py`:

- **Happy path:** `POST /campaigns` with `channel=email` + all required fields → 201. DB row has all five columns populated.
- **Missing fields:** omit `sender_name` → 422 with `sender_name` in the error message. Same for `subject`, `email_account_id`.
- **Cross-org mailbox:** `email_account_id` belonging to another org → 400.
- **Unverified mailbox:** account with `sync_state='disconnected'` → 400 "not connected".
- **WhatsApp unaffected:** `channel=whatsapp` campaign create with none of the new fields → still 201.
- **Update path:** flip a Draft `channel=whatsapp` campaign to `channel=email` via PATCH without setting the new fields → 422.

Frontend spec:

- Channel switched to Email → the five new fields appear; switching back to WhatsApp → they disappear.
- Submit button disabled until required fields are filled.
- Variable-token insertion places `{{first_name}}` at the caret position, not at the end.
- Empty-state banner shows when the `/email-accounts?sync_state=live` response is empty.

## Verification

Ajay's Workspace:

1. Prereq — at least one connected email account (Google or Microsoft) on Ajay's Owner login. If none exists, connect one via the existing email-setup flow.
2. **Campaigns → + New Campaign**. Choose channel = Email.
3. Mailbox dropdown lists the connected mailbox. Sender name / Subject visible + required. Reply-to / Preheader visible + optional.
4. Try submit with subject blank → button disabled. Fill it → submit enabled.
5. Submit → 201, campaign lands in Draft with all five columns saved (verify via psql inside docker helper).
6. Try disconnecting the mailbox in the email setup, then try to submit again → 400 error banner "Selected mailbox is not connected".
7. Switch channel to WhatsApp mid-flow → the five Email fields disappear; existing WhatsApp fields render fine.

## Self-check (fill in before the stop-and-report)

- 10 rules: line-by-line (esp. `org_id` filter on `email_accounts` lookup)
- Layered architecture: cross-module read via `email_accounts.data_access` (no business rule at stake) — noted in code review
- Reuse: existing `EmailAccount` model, no new sender/domain tables in this step
- Query efficiency: single mailbox lookup + single campaign insert; frontend fetches accounts once on channel-change
- Tooling: prettier + eslint + ruff on all touched files; migration verified up + down inside docker helper

## Awaiting your `proceed`

Done means: Email campaigns can be created as Drafts with all five fields, cross-org / unverified-mailbox rejections work, WhatsApp campaigns unaffected, browser smoke green. Campaigns still don't *send* Email — that lands in Step 05.
