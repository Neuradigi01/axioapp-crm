# Step 3 — `core/email/mailgun/` webhook + signature + payload-to-disk + Celery enqueue

**Status:** Pending
**Effort:** ~0.75 day
**Depends on:** Step 1 (DLQ table exists for later use).
**Blocks:** Step 4 (ingest depends on this endpoint).

## Goal

Ship the public webhook endpoint that:
1. Verifies Mailgun signature (constant-time HMAC + 5-min timestamp + 10-min replay cache).
2. Persists raw payload + attachments to `./storage/pending-inbound/{uuid}/` on disk.
3. Enqueues a Celery task with the path.
4. Returns 200 in constant time regardless of token validity.

Also ships the health-check endpoint and the pending-inbound sweeper for broker-down recovery.

## Scope

**Webhook router** — `api/src/app/core/email/mailgun/router.py`:

```python
@router.post("/webhook/mailgun/inbound")
async def mailgun_inbound(request: Request) -> JSONResponse:
    body = await request.body()  # multipart/form-data raw
    form = await request.form()

    timestamp = form.get("timestamp", "")
    token = form.get("token", "")
    signature = form.get("signature", "")

    # Fail-CLOSED on Redis outage during signature/replay check.
    if not await _verify_signature(timestamp, token, signature):
        client_ip = request.client.host if request.client else None
        # Rate-limit ONLY signature failures.
        await rate_hit(f"mgw:fail:{client_ip}", 20, 60)
        await audit.log(
            "mailgun.webhook.invalid_signature",
            entity_type="webhook_attempt",
            after={"reason": "bad_signature"},
            org_id=None,  # system-level
            ip=client_ip,
        )
        return JSONResponse(status_code=401, content={"error": "bad signature"})

    if not await _check_and_record_replay(token):
        return JSONResponse(status_code=401, content={"error": "replay"})

    # Persist raw payload + attachments to disk BEFORE enqueue.
    pending_dir = await mailgun_service.persist_pending_inbound(form)

    # Enqueue task with the path. Broker down? Sweeper picks up later.
    try:
        process_mailgun_inbound.delay(str(pending_dir))
    except Exception:
        logger.exception("mailgun webhook: enqueue failed for %s", pending_dir)
        # Return 200 — pending-inbound sweeper will re-enqueue.

    return JSONResponse(status_code=200, content={"status": "accepted"})
```

**Signature verify** — `api/src/app/core/email/mailgun/service.py`:

```python
async def _verify_signature(timestamp: str, token: str, signature: str) -> bool:
    if not (timestamp and token and signature):
        return False
    # 5-min window.
    try:
        ts_int = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - ts_int) > 300:
        return False

    current_key = os.getenv("MAILGUN_SIGNING_KEY", "")
    previous_key = os.getenv("MAILGUN_SIGNING_KEY_PREVIOUS", "")
    if not current_key:
        logger.error("mailgun: MAILGUN_SIGNING_KEY not set — rejecting all")
        return False

    signed = (timestamp + token).encode("utf-8")
    for key in (current_key, previous_key):
        if not key:
            continue
        expected = hmac.new(key.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature):
            return True
    return False
```

**Replay cache** — `api/src/app/core/email/mailgun/data_access.py`:

```python
async def check_and_record_replay(token: str) -> bool:
    """Return True if token unseen; False if already seen (replay). Fail-CLOSED on Redis outage."""
    r = await get_redis()
    try:
        # SET NX with 10-min TTL. Returns True if new, False if key already existed.
        return bool(await r.set(f"mgw:seen:{token}", "1", ex=600, nx=True))
    except Exception:
        logger.error("mailgun: redis outage on replay check — failing closed")
        return False
```

**Pending-inbound persistence** — `service.py`:

```python
async def persist_pending_inbound(form) -> Path:
    request_id = uuid.uuid4()
    pending_dir = Path(STORAGE_ROOT) / "pending-inbound" / str(request_id)
    pending_dir.mkdir(parents=True, exist_ok=True)

    # Write metadata (form fields as JSON).
    metadata = {k: v for k, v in form.items() if not hasattr(v, "filename")}
    (pending_dir / "payload.json").write_text(json.dumps(metadata))

    # Write attachments (multipart file parts).
    for k, v in form.items():
        if hasattr(v, "filename") and v.filename:
            safe_name = _sanitize_filename(v.filename)
            with open(pending_dir / f"attachment_{k}_{safe_name}", "wb") as f:
                f.write(await v.read())

    return pending_dir
```

**Pending-inbound sweeper** — `api/src/app/core/email/mailgun/pending_inbound_sweeper.py`:

- Celery beat task, every 5 min.
- Scans `./storage/pending-inbound/` for directories older than 5 min.
- Re-enqueues `process_mailgun_inbound.delay(str(path))` for each.
- Success case: worker deletes the directory (Step 4 owns that).

**Celery task stub** — `api/src/app/core/email/mailgun/tasks.py`:

- `@celery_app.task(bind=True, max_retries=3, autoretry_for=(Exception,))`
- `process_mailgun_inbound(self, pending_path: str)` — Step 3 ships a stub that logs; Step 4 wires the real ingest.

**Health-check** — `router.py`:

- `GET /api/v1/webhooks/mailgun/inbound/health` → `{"ok": true, "domain": MAILGUN_DOMAIN}`. No auth.

**Register router** — `api/src/app/main.py`:

- `app.include_router(mailgun_router, prefix="/api/v1/webhooks")`.

**Beat entry** — `api/src/app/shared/celery_config.py`:

- Add `mailgun-pending-inbound-sweep` beat entry, 300s (5 min).

## Files touched

- `api/src/app/core/email/mailgun/router.py` (new)
- `api/src/app/core/email/mailgun/service.py` (new — signature verify + persist)
- `api/src/app/core/email/mailgun/data_access.py` (new — replay cache)
- `api/src/app/core/email/mailgun/tasks.py` (new — Celery worker stub)
- `api/src/app/core/email/mailgun/pending_inbound_sweeper.py` (new)
- `api/src/app/main.py` — register router.
- `api/src/app/shared/celery_config.py` — beat entry.
- `api/config.env` — `MAILGUN_DOMAIN`, `INBOUND_EMAIL_DOMAIN`, `MAILGUN_WEBHOOK_URL`.
- `api/secrets.enc.env` — `MAILGUN_API_KEY`, `MAILGUN_SIGNING_KEY`, `MAILGUN_SIGNING_KEY_PREVIOUS`.

## Tests

- `test_webhook_rejects_missing_signature_header`
- `test_webhook_rejects_bad_signature_returns_401`
- `test_webhook_accepts_valid_signature_returns_200`
- `test_webhook_signature_input_is_timestamp_concat_token_exactly` (byte-sequence assertion via monkeypatch on `hmac.new`)
- `test_webhook_signature_verify_uses_constant_time_compare` (assert `hmac.compare_digest` called)
- `test_webhook_rejects_timestamp_older_than_5min_returns_401`
- `test_webhook_rejects_timestamp_in_future_by_more_than_5min`
- `test_webhook_replay_token_rejected_within_10min_window`
- `test_webhook_replay_token_accepted_after_10min_window`
- `test_webhook_signing_key_missing_rejects_all_returns_401`
- `test_webhook_fallback_to_previous_signing_key_during_rotation`
- `test_webhook_rate_limit_only_on_signature_failures_not_signed`
- `test_webhook_redis_down_signature_check_fails_closed`
- `test_webhook_redis_down_rate_limiter_fails_open`
- `test_webhook_request_time_constant_regardless_of_token_validity` (measure elapsed for 100 valid + 100 invalid tokens; assert 95th percentiles within 20ms)
- `test_webhook_persists_payload_to_pending_inbound_before_enqueue`
- `test_webhook_returns_200_after_disk_write`
- `test_webhook_returns_200_even_if_enqueue_fails` (broker down simulation)
- `test_cron_sweeper_reenqueues_pending_inbound_older_than_5min`
- `test_health_endpoint_returns_ok_no_auth`

## Self-check

- [ ] HMAC input is EXACTLY `(timestamp + token).encode("utf-8")` — nothing else.
- [ ] `hmac.compare_digest` used (constant-time).
- [ ] Signing-key fallback tries current first, then previous.
- [ ] Rate limiter ONLY on signature-verify failures.
- [ ] Redis outage: signature check fails CLOSED (401); rate limiter fails OPEN (allow).
- [ ] Payload persisted to disk BEFORE `.delay()` call.
- [ ] Return 200 even if enqueue raises.
- [ ] Sweeper cadence 5 min.
- [ ] No DB writes in the webhook request path (constant-time).
- [ ] `MAILGUN_SIGNING_KEY_PREVIOUS` empty-by-default in `secrets.enc.env`.
- [ ] Path `pending-inbound` outside org-scoped storage (there's no org yet — token not resolved).

## Report template

```
Files changed: <list>

Manual verify (staging):
  1. `curl http://staging/api/v1/webhooks/mailgun/inbound/health` → 200 with domain.
  2. Send raw multipart POST with random signature → 401 audit event.
  3. Send with valid Mailgun-format signature → 200. Directory appears under `./storage/pending-inbound/<uuid>/`.
  4. Replay same request within 10 min → 401.
  5. Stop broker, POST valid → 200, directory persists, sweeper re-enqueues on broker recovery.

Tests: 20 pytest.

Self-check: all pass.

Awaiting proceed for Step 4.
```
