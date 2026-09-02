# Step 1 — Backend schema + DAL foundations

**Status:** Pending
**Effort:** ~0.5 day
**Depends on:** Step 0 (dedup index exists).
**Blocks:** Steps 2–5.

## Goal

Ship all schema + DAL primitives every later step depends on:

- `tbl_email_smtp_senders`: `inbound_token VARCHAR(32) UNIQUE`, `capture_replies_in_crm BOOLEAN NOT NULL DEFAULT true`.
- `tbl_messages`: `spf_result VARCHAR(16)`, `dkim_result VARCHAR(16)`.
- New table `tbl_email_inbound_dlq`.
- Backfill inbound_tokens for existing SMTP senders.
- New DAL: `find_contact_by_email(session, *, org_id, email)`.
- New DAL: `find_by_inbound_token(session, token)` on `email_senders`.

## Scope

**Migration:**

- `tbl_email_smtp_senders`:
  - `inbound_token VARCHAR(32) NULL` initially, backfill in same migration, then `ALTER COLUMN inbound_token SET NOT NULL` + `ADD CONSTRAINT uq_email_smtp_senders_inbound_token UNIQUE (inbound_token)`.
  - `capture_replies_in_crm BOOLEAN NOT NULL DEFAULT true`.
- `tbl_messages`:
  - `spf_result VARCHAR(16) NULL` (values: `pass|fail|softfail|neutral|none|null`).
  - `dkim_result VARCHAR(16) NULL` (values: `pass|fail|none|null`).
- New `tbl_email_inbound_dlq`:
  ```
  id UUID PK default gen_random_uuid()
  org_id UUID NULL FK tbl_organizations(id) ON DELETE CASCADE
  mailgun_delivery_id VARCHAR(64) NULL
  pending_inbound_path TEXT NOT NULL
  error_reason VARCHAR(64) NOT NULL
  error_details JSONB NULL
  retry_count INTEGER NOT NULL DEFAULT 0
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  resolved_at TIMESTAMPTZ NULL
  ```
  Index on `(org_id, created_at DESC)` for admin listing.
- **Backfill** in a Python function inside the migration:
  ```python
  def _backfill_tokens(bind):
      import secrets
      # Idempotent: only WHERE inbound_token IS NULL
      rows = bind.execute(text("SELECT id FROM tbl_email_smtp_senders WHERE inbound_token IS NULL")).fetchall()
      for (sender_id,) in rows:
          for _ in range(10):
              tok = secrets.token_urlsafe(9)[:12]
              try:
                  bind.execute(
                      text("UPDATE tbl_email_smtp_senders SET inbound_token = :t WHERE id = :i AND inbound_token IS NULL"),
                      {"t": tok, "i": sender_id},
                  )
                  break
              except Exception:
                  continue
  ```

**ORM:**

- `core/email_senders/models.py` — add `inbound_token: Mapped[str]` and `capture_replies_in_crm: Mapped[bool]`.
- `core/conversations/models.py` — add `spf_result: Mapped[str | None]` and `dkim_result: Mapped[str | None]` on `Message`.
- `core/email/mailgun/dlq_models.py` — `EmailInboundDlq` ORM class (lives here, not in `email_senders/`, because DLQ is Mailgun-specific bookkeeping).

**DAL:**

- `core/email_senders/data_access.py` — add `find_by_inbound_token(session, token: str) -> EmailSmtpSender | None`.
- `core/contacts/data_access.py` — add:
  ```python
  async def find_contact_by_email(session, *, org_id, email: str) -> Contact | None:
      normalized = email.strip().lower()
      stmt = (
          select(Contact)
          .where(Contact.org_id == org_id, func.lower(Contact.primary_email) == normalized)
          .order_by(Contact.updated_at.desc())
          .limit(1)
      )
      return (await session.execute(stmt)).scalar_one_or_none()
  ```
  Uses `primary_email` — verify column name in Step 1 exploration; if different, use actual name.

## Files touched

- `api/alembic/versions/0XXX_mailgun_inbound_schema.py` (single migration)
- `api/src/app/core/email_senders/models.py`
- `api/src/app/core/email_senders/data_access.py`
- `api/src/app/core/conversations/models.py`
- `api/src/app/core/contacts/data_access.py`
- `api/src/app/core/email/mailgun/__init__.py` (new, empty)
- `api/src/app/core/email/mailgun/dlq_models.py` (new)

## Tests

- `test_step1_migration_adds_inbound_token_column`
- `test_step1_migration_adds_capture_replies_in_crm_column_default_true`
- `test_step1_migration_backfills_existing_smtp_senders`
- `test_step1_backfill_idempotent_on_partial_crash_retry`
- `test_step1_migration_adds_spf_dkim_columns_on_messages`
- `test_step1_migration_creates_tbl_email_inbound_dlq`
- `test_step1_migration_down_removes_all_changes`
- `test_find_by_inbound_token_returns_sender`
- `test_find_by_inbound_token_returns_none_when_absent`
- `test_find_contact_by_email_returns_none_when_no_match`
- `test_find_contact_by_email_returns_single_match`
- `test_find_contact_by_email_returns_most_recently_updated_on_tie`
- `test_find_contact_by_email_lowercases_input`
- `test_find_contact_by_email_scoped_by_org_id_no_cross_org_leak`

## Self-check

- [ ] Revision ID ≤ 32 chars.
- [ ] Backfill idempotent (WHERE `inbound_token IS NULL`).
- [ ] Backfill retries 10× on collision.
- [ ] `NOT NULL + UNIQUE` on `inbound_token` applied AFTER backfill completes.
- [ ] All new columns in `tbl_*` tables (naming rule).
- [ ] DAL functions don't call `db.commit/flush/refresh` (layered convention).
- [ ] `find_contact_by_email` filters by `org_id` in the WHERE clause (not just relying on RLS).

## Report template

```
Files changed: <list>

Migration applied: staging + prod.
Backfilled tokens for N existing SMTP senders.

Sample tokens generated: <5 examples, redacted middle chars>

What you can verify:
  - `\d tbl_email_smtp_senders` shows inbound_token + capture_replies_in_crm.
  - `\d tbl_messages` shows spf_result + dkim_result.
  - `\d tbl_email_inbound_dlq` exists.
  - `SELECT COUNT(*) FROM tbl_email_smtp_senders WHERE inbound_token IS NULL;` returns 0.

Tests: 14 pytest.

Self-check: all pass.

Awaiting proceed for Step 2.
```
