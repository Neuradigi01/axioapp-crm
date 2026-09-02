# Step 4 — Ingest service + shared `_persist_inbound_email` refactor + SPF/DKIM enforcement + auto-responder detection

**Status:** COMPLETED — 2026-09-02. Shared `_persist_inbound_email` extracted (OAuth `receive_email` refactored to wrap it, byte-shape identical); threading DALs take `org_id` explicitly (Attacker C3 fix); Mailgun task body wires token→sender→org resolution + SPF/DKIM enforcement + auto-responder detection + multi-recipient guard + DLQ on exhausted retries.
**Effort:** ~1 day (actual: ~2 hours).
**Depends on:** Steps 1 (schema + DAL), 3 (webhook writes pending-inbound).
**Blocks:** Step 5 (attachments extend this), Step 7 (end-to-end smoke).

## Goal

Wire the Mailgun Celery task to persist a real `Message`. This is where the substantive logic lives:

1. Refactor `receive_email` in `core/conversations/adapters/email.py` to extract `_persist_inbound_email(session, *, org_id, contact_id, headers, body_text, body_html, attachments, channel_message_id, spf_result, dkim_result, source_provider, source_reference)`. OAuth callers keep behavior byte-identical.
2. Mailgun task: parse pending-inbound → resolve token → SPF/DKIM check → auto-responder detection → contact match → call shared helper → publish workflow events → cleanup.
3. Threading queries take `org_id` **explicitly** — never rely on session-scoped tenant context alone.

## Scope

**Extract `_persist_inbound_email` from `receive_email`:**

- File: `api/src/app/core/conversations/adapters/email.py`.
- Move lines 599–744 (the body of `receive_email` after the dedup + threading + persist) into a new module-level `async def _persist_inbound_email(...)`.
- `receive_email(account, matched)` becomes a thin wrapper that maps its inputs to the shared helper's args.
- Shared helper signature:
  ```python
  async def _persist_inbound_email(
      session,
      *,
      org_id: uuid.UUID,
      contact_id: uuid.UUID | None,
      headers: dict[str, str],
      body_text: str,
      body_html: str | None,
      attachments: list[dict],
      channel_message_id: str,
      spf_result: str | None,
      dkim_result: str | None,
      auto_generated: bool,
      source_provider: str,             # "gmail" | "microsoft" | "mailgun"
      source_reference: dict,           # provider-specific bookkeeping
      publish_workflow_events: bool,    # False when spoof_suspected or auto_generated
  ) -> Message | None:
  ```
- **All threading DAL calls inside pass `org_id` explicitly** — not session context alone. Update `_find_conversation_by_thread_keys` and `_find_latest_email_conversation_for_contact` signatures to require `org_id`.

**Mailgun ingest task** — `api/src/app/core/email/mailgun/tasks.py`:

```python
@celery_app.task(bind=True, max_retries=3, autoretry_for=(Exception,), retry_backoff=True)
def process_mailgun_inbound(self, pending_path: str):
    asyncio.run(_process_async(self, pending_path))

async def _process_async(task, pending_path: str):
    path = Path(pending_path)
    if not path.exists():
        logger.info("mailgun: pending path missing, likely already processed: %s", path)
        return

    payload = json.loads((path / "payload.json").read_text())
    mailgun_delivery_id = payload.get("Message-Id") or payload.get("message-id") or ""
    if not mailgun_delivery_id:
        await _fail_to_dlq(path, "missing_mailgun_delivery_id", payload)
        return

    recipient = payload.get("recipient", "")
    token = _extract_token(recipient)  # "in_xxx@..." -> "xxx"
    if not token:
        await audit.log("mailgun.inbound.unknown_recipient", ..., org_id=None)  # system-level
        _cleanup(path)
        return

    # Multi-recipient guard.
    other_tokens = _extract_all_tokens(payload)
    if len(other_tokens) > 1:
        await audit.log("mailgun.inbound.multi_recipient", ..., org_id=None)
        _cleanup(path)
        return

    async with async_session() as session:
        sender = await email_senders_da.find_by_inbound_token(session, token)
        if sender is None:
            await audit.log("mailgun.inbound.unknown_recipient", ..., org_id=None)
            _cleanup(path)
            return

        org_id = sender.org_id
        await session.execute(text("SET LOCAL app.current_org_id = :o"), {"o": str(org_id)})

        # Org health.
        org = await tenants_da.get_by_id(session, org_id)
        if org is None:
            await audit.log("mailgun.inbound.deleted_org", ..., org_id=None)
            _cleanup(path); return
        if org.status == "suspended":
            await audit.log("mailgun.inbound.org_suspended", ..., org_id=org_id)
            _cleanup(path); return

        # SPF / DKIM parse from Mailgun payload.
        spf_result = _parse_spf(payload)
        dkim_result = _parse_dkim(payload)

        # Auto-responder detection.
        headers = _extract_headers(payload)
        auto_generated = _detect_auto_responder(headers)

        # Contact match.
        sender_email = _extract_sender_email(payload)
        contact = await contacts_da.find_contact_by_email(session, org_id=org_id, email=sender_email)
        contact_id = contact.id if contact else None

        # Spoof enforcement: SPF-fail OR DKIM-fail + matching contact → NULL contact + skip workflow events.
        spoof_suspected = (spf_result == "fail" or dkim_result == "fail") and contact_id is not None
        if spoof_suspected:
            contact_id = None
            await audit.log(
                "mailgun.inbound.sender_auth_failed",
                after={"sender_email": sender_email, "spf": spf_result, "dkim": dkim_result},
                org_id=org_id,
            )

        publish_events = not (spoof_suspected or auto_generated)

        # Attachments handled in Step 5 — for Step 4, pass empty list.
        message = await _persist_inbound_email(
            session,
            org_id=org_id,
            contact_id=contact_id,
            headers=headers,
            body_text=payload.get("body-plain", ""),
            body_html=payload.get("body-html"),
            attachments=[],
            channel_message_id=f"mg:{mailgun_delivery_id}",
            spf_result=spf_result,
            dkim_result=dkim_result,
            auto_generated=auto_generated,
            source_provider="mailgun",
            source_reference={"smtp_sender_id": str(sender.id), "mailgun_delivery_id": mailgun_delivery_id},
            publish_workflow_events=publish_events,
        )

    _cleanup(path)
```

**Auto-responder detection helper:**

```python
def _detect_auto_responder(headers: dict[str, str]) -> bool:
    auto_submitted = headers.get("auto-submitted", "").strip().lower()
    if auto_submitted and auto_submitted != "no":
        return True
    precedence = headers.get("precedence", "").strip().lower()
    if precedence in {"bulk", "junk", "list"}:
        return True
    suppress = headers.get("x-auto-response-suppress", "").strip().lower()
    if suppress in {"all", "oof", "autoreply"}:
        return True
    return False
```

**DLQ handling:**

```python
async def _fail_to_dlq(path: Path, reason: str, payload: dict, org_id: UUID | None = None):
    async with async_session() as session:
        dlq_row = EmailInboundDlq(
            org_id=org_id,
            mailgun_delivery_id=payload.get("Message-Id"),
            pending_inbound_path=str(path),
            error_reason=reason,
            error_details={"payload_summary": {k: v for k, v in payload.items() if k in ("recipient", "sender", "subject")}},
            retry_count=0,
        )
        session.add(dlq_row)
        await session.commit()
```

Called when Celery `max_retries` is exhausted (task-level `on_failure` handler).

## Files touched

- `api/src/app/core/conversations/adapters/email.py` — extract `_persist_inbound_email`, add `org_id` to threading DALs.
- `api/src/app/core/email/mailgun/tasks.py` — real ingest logic (replaces Step 3 stub).
- `api/src/app/core/email/mailgun/service.py` — DLQ writer, SPF/DKIM parsers, auto-responder detector, token extractor.
- `api/src/app/core/email/mailgun/data_access.py` — DLQ CRUD.
- `api/src/app/core/conversations/models.py` — no change (columns added in Step 1).

## Tests

- `test_persist_helper_takes_org_id_explicitly`
- `test_persist_helper_threading_dal_calls_carry_org_id`
- `test_oauth_receive_email_byte_identical_output_after_refactor` (persist a message via OAuth path, snapshot DB state; refactor; assert identical)
- `test_ingest_resolves_org_from_inbound_token`
- `test_ingest_unknown_recipient_audits_system_level_not_tenant`
- `test_ingest_multi_recipient_payload_rejected_with_audit`
- `test_ingest_deleted_org_audits_and_drops`
- `test_ingest_suspended_org_audits_and_drops`
- `test_ingest_sets_rls_context_before_dbwrite`
- `test_ingest_spf_pass_dkim_pass_attributes_to_contact`
- `test_ingest_spf_fail_matching_contact_sets_null_contact_and_flags`
- `test_ingest_dkim_fail_matching_contact_sets_null_contact_and_flags`
- `test_ingest_spf_fail_no_matching_contact_persists_normally`
- `test_ingest_auth_fail_skips_email_replied_workflow_event`
- `test_ingest_persists_spf_and_dkim_columns_on_message`
- `test_ingest_auto_submitted_yes_flags_auto_generated`
- `test_ingest_precedence_bulk_flags_auto_generated`
- `test_ingest_x_auto_response_suppress_flags_auto_generated`
- `test_ingest_auto_generated_skips_workflow_events`
- `test_mailgun_channel_message_id_uses_mg_prefix_and_delivery_id`
- `test_attacker_cannot_reserve_channel_message_id_via_rfc_message_id` (attacker POSTs Message-ID identical to a legit one; both persist because keyed on mailgun delivery id)
- `test_duplicate_delivery_second_insert_rejected_by_partial_index`
- `test_cross_org_message_id_never_threads_to_wrong_org`
- `test_cross_org_contact_lookup_scoped_by_org_id`
- `test_dlq_row_written_when_max_retries_exhausted`

## Self-check

- [ ] `_persist_inbound_email` signature exactly as specced.
- [ ] Every threading DAL call inside the helper carries `org_id` (grep the helper for calls to `_find_conversation*` — each must take `org_id=`).
- [ ] OAuth `receive_email` still works — byte-identical assertion test passes.
- [ ] `channel_message_id` uses `mg:<mailgun_delivery_id>`, never RFC Message-ID.
- [ ] SPF/DKIM fail + matching contact → `contact_id=None` in persisted row.
- [ ] Auto-responder detected → `publish_workflow_events=False`.
- [ ] Multi-recipient payload → reject before any DB write.
- [ ] Suspended/deleted org → drop, no persist.
- [ ] `SET LOCAL app.current_org_id` set AFTER token resolution, BEFORE any writes.
- [ ] DLQ writer callable from Celery `on_failure`.
- [ ] No sync DB calls in webhook path (all in Celery task) — request stays constant-time.

## Report template

```
Files changed: <list>

Manual verify (staging, sandbox Mailgun):
  1. Send a signed test POST to /api/v1/webhooks/mailgun/inbound with recipient=in_<real_token>@sandbox... → 200.
  2. Watch Celery: task runs, message persisted to correct org's conversation.
  3. Send with SPF=fail header → message persists with contact_id=NULL, audit event visible.
  4. Send with Auto-Submitted: auto-replied → message persists, no workflow event fired.
  5. Send with recipient=in_bogus@... → 200, unknown_recipient audit (system-level).
  6. Send same delivery twice → second one dropped by unique index, no duplicate row.

Tests: 25 pytest.

Self-check: all pass.

Awaiting proceed for Step 5.
```
