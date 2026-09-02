"""Coverage for Step 3 of the mailgun-inbound track.

Two surfaces:

  1. ``service.verify_signature`` — pure HMAC helper. Tested with
     stub timestamp/token/signature triplets.
  2. ``POST /api/v1/webhooks/mailgun/inbound`` — public endpoint via
     ``layered_client``. Signature failure = 401 + audit; signed
     delivery = 200 + on-disk pending directory + enqueued task
     (mocked to avoid a real broker).

The Celery task body itself is a Step-3 stub — Step 4 fills it. Here
we only assert it *was called* with the persisted path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.app.core.email.mailgun import service


# ---------------------------------------------------------------------------
# verify_signature — pure HMAC
# ---------------------------------------------------------------------------


def _sign(*, key: str, timestamp: str, token: str) -> str:
    return hmac.new(
        key.encode("utf-8"),
        (timestamp + token).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def test_verify_signature_accepts_valid_current_key(monkeypatch):
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "current-key")
    monkeypatch.delenv("MAILGUN_SIGNING_KEY_PREVIOUS", raising=False)
    ts = str(int(time.time()))
    tok = "delivery-token-xyz"
    sig = _sign(key="current-key", timestamp=ts, token=tok)
    assert service.verify_signature(timestamp=ts, token=tok, signature=sig) is True


def test_verify_signature_rejects_bad_signature(monkeypatch):
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "current-key")
    ts = str(int(time.time()))
    assert (
        service.verify_signature(timestamp=ts, token="tok", signature="deadbeef")
        is False
    )


def test_verify_signature_rejects_missing_signing_key(monkeypatch):
    """Fail-CLOSED — no key means we reject every request rather than
    accepting unsigned traffic."""
    monkeypatch.delenv("MAILGUN_SIGNING_KEY", raising=False)
    monkeypatch.delenv("MAILGUN_SIGNING_KEY_PREVIOUS", raising=False)
    ts = str(int(time.time()))
    sig = _sign(key="whatever", timestamp=ts, token="tok")
    assert service.verify_signature(timestamp=ts, token="tok", signature=sig) is False


def test_verify_signature_rejects_timestamp_older_than_5min(monkeypatch):
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    ts = str(int(time.time()) - 600)  # 10 min ago
    sig = _sign(key="k", timestamp=ts, token="tok")
    assert service.verify_signature(timestamp=ts, token="tok", signature=sig) is False


def test_verify_signature_rejects_timestamp_in_far_future(monkeypatch):
    """Clock-skew guard both directions — attacker can't backdate OR
    postdate to slip through."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    ts = str(int(time.time()) + 600)
    sig = _sign(key="k", timestamp=ts, token="tok")
    assert service.verify_signature(timestamp=ts, token="tok", signature=sig) is False


def test_verify_signature_rejects_non_integer_timestamp(monkeypatch):
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    sig = _sign(key="k", timestamp="not-a-number", token="tok")
    assert (
        service.verify_signature(timestamp="not-a-number", token="tok", signature=sig)
        is False
    )


def test_verify_signature_rejects_empty_fields(monkeypatch):
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    assert service.verify_signature(timestamp="", token="tok", signature="sig") is False
    assert service.verify_signature(timestamp="0", token="", signature="sig") is False
    assert service.verify_signature(timestamp="0", token="tok", signature="") is False


def test_verify_signature_falls_back_to_previous_key_during_rotation(monkeypatch):
    """Zero-loss rotation window: promote current → previous, install
    a new current. Both keys must verify until previous is dropped."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "new-key")
    monkeypatch.setenv("MAILGUN_SIGNING_KEY_PREVIOUS", "old-key")
    ts = str(int(time.time()))
    tok = "some-token"
    # Signed with the OLD key — must still verify.
    sig = _sign(key="old-key", timestamp=ts, token=tok)
    assert service.verify_signature(timestamp=ts, token=tok, signature=sig) is True
    # Signed with the NEW key — also verifies.
    sig_new = _sign(key="new-key", timestamp=ts, token=tok)
    assert service.verify_signature(timestamp=ts, token=tok, signature=sig_new) is True


def test_verify_signature_previous_key_empty_falls_through_to_reject(monkeypatch):
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "new-key")
    monkeypatch.setenv("MAILGUN_SIGNING_KEY_PREVIOUS", "")
    ts = str(int(time.time()))
    sig = _sign(key="old-key", timestamp=ts, token="tok")
    assert service.verify_signature(timestamp=ts, token="tok", signature=sig) is False


def test_verify_signature_hmac_input_is_exactly_timestamp_concat_token(monkeypatch):
    """Byte-sequence assertion — implementer MUST NOT deviate from
    ``(timestamp + token).encode("utf-8")``. Any Stripe-shaped bug
    where only ``timestamp`` is signed is caught here."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    ts = "1234567890"
    tok = "abc"
    # Deliberately compute against a DIFFERENT input shape (just ts)
    # — the helper must reject it.
    bad_sig = hmac.new(b"k", ts.encode("utf-8"), hashlib.sha256).hexdigest()
    assert service.verify_signature(timestamp=ts, token=tok, signature=bad_sig) is False


# ---------------------------------------------------------------------------
# persist_pending_inbound — on-disk layout
# ---------------------------------------------------------------------------


class _FakeUploadFile:
    """Duck-typed Starlette UploadFile substitute for
    ``persist_pending_inbound`` tests — the helper only reads
    ``.filename`` and ``.read()``."""

    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _FakeMultipartForm:
    """FormData substitute exposing ``multi_items`` in the same order
    Starlette does."""

    def __init__(self, items: list[tuple[str, object]]):
        self._items = items

    def multi_items(self):
        return list(self._items)


@pytest.mark.asyncio
async def test_persist_pending_inbound_writes_payload_and_attachments(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    form = _FakeMultipartForm(
        [
            ("timestamp", "1234"),
            ("token", "tok"),
            ("signature", "sig"),
            ("recipient", "in_abc@example.com"),
            ("sender", "customer@ex.com"),
            ("subject", "Hello"),
            ("body-plain", "Hi there"),
            ("attachment-1", _FakeUploadFile("photo.png", b"\x89PNG-fake")),
        ]
    )
    pending_dir = await service.persist_pending_inbound(form)

    assert pending_dir.exists() and pending_dir.is_dir()
    payload = json.loads((pending_dir / "payload.json").read_text())
    assert payload["recipient"] == "in_abc@example.com"
    assert payload["body-plain"] == "Hi there"
    # UploadFile fields aren't in the payload JSON — only in _attachments.
    assert "attachment-1" not in payload
    assert payload["_attachments"] == [{"index": 0, "filename": "photo.png"}]
    # File was written under the pending dir with the sanitised name.
    attachment_files = list(pending_dir.glob("attachment_0_*"))
    assert len(attachment_files) == 1
    assert attachment_files[0].read_bytes() == b"\x89PNG-fake"


@pytest.mark.asyncio
async def test_persist_pending_inbound_sanitises_path_traversal_filename(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    form = _FakeMultipartForm(
        [
            ("attachment-1", _FakeUploadFile("../../../etc/passwd", b"x")),
        ]
    )
    pending_dir = await service.persist_pending_inbound(form)
    # The dangerous path fragments must not appear as directories.
    for entry in pending_dir.iterdir():
        assert ".." not in entry.name
        assert "/" not in entry.name
        assert "\\" not in entry.name


@pytest.mark.asyncio
async def test_persist_pending_inbound_preserves_repeated_string_fields(
    tmp_path, monkeypatch
):
    """Mailgun's ``recipient`` can appear multiple times if a delivery
    had ``To`` + ``Cc`` addresses. The persist step must preserve the
    list shape so Step 4's multi-recipient guard can inspect it."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    form = _FakeMultipartForm(
        [
            ("recipient", "in_a@example.com"),
            ("recipient", "in_b@example.com"),
        ]
    )
    pending_dir = await service.persist_pending_inbound(form)
    payload = json.loads((pending_dir / "payload.json").read_text())
    assert payload["recipient"] == ["in_a@example.com", "in_b@example.com"]


# ---------------------------------------------------------------------------
# enqueue_process_task — soft-fail
# ---------------------------------------------------------------------------


def test_enqueue_process_task_returns_true_on_success(tmp_path):
    with patch(
        "src.app.core.email.mailgun.tasks.process_mailgun_inbound.delay"
    ) as mock_delay:
        mock_delay.return_value = None
        assert service.enqueue_process_task(tmp_path) is True
        mock_delay.assert_called_once_with(str(tmp_path))


def test_enqueue_process_task_returns_false_when_broker_refuses(tmp_path):
    """Broker outage after our 200 → sweeper picks up later.
    The webhook must not raise — service returns False silently."""
    with patch(
        "src.app.core.email.mailgun.tasks.process_mailgun_inbound.delay",
        side_effect=RuntimeError("broker down"),
    ):
        assert service.enqueue_process_task(tmp_path) is False


# ---------------------------------------------------------------------------
# HTTP layer — POST /api/v1/webhooks/mailgun/inbound
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature_returns_401(
    layered_client, monkeypatch, tmp_path
):
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    resp = await layered_client.post(
        "/api/v1/webhooks/mailgun/inbound",
        data={
            "timestamp": str(int(time.time())),
            "token": "some-token",
            "signature": "deadbeef",
            "recipient": "in_abc@ex.com",
        },
    )
    assert resp.status_code == 401
    body = resp.json()
    assert "bad signature" in body["error"].lower()


@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature_fields_returns_401(
    layered_client, monkeypatch, tmp_path
):
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    resp = await layered_client.post(
        "/api/v1/webhooks/mailgun/inbound",
        data={"recipient": "in_abc@ex.com"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_accepts_signed_delivery_persists_and_enqueues(
    layered_client, monkeypatch, tmp_path
):
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    ts = str(int(time.time()))
    tok = "delivery-token-fresh"
    sig = _sign(key="k", timestamp=ts, token=tok)

    with patch(
        "src.app.core.email.mailgun.tasks.process_mailgun_inbound.delay"
    ) as mock_delay:
        resp = await layered_client.post(
            "/api/v1/webhooks/mailgun/inbound",
            data={
                "timestamp": ts,
                "token": tok,
                "signature": sig,
                "recipient": "in_abc@ex.com",
                "sender": "customer@ex.com",
                "subject": "Test",
                "body-plain": "Body",
            },
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted"}
    # Enqueue was called with the pending path.
    mock_delay.assert_called_once()
    pending_arg = mock_delay.call_args.args[0]
    assert Path(pending_arg).exists()
    assert Path(pending_arg).parent.name == "pending-inbound"


@pytest.mark.asyncio
async def test_webhook_replay_rejected_second_time(
    layered_client, monkeypatch, tmp_path
):
    """Same signed triplet posted twice → second one 401s (replay)."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    ts = str(int(time.time()))
    tok = f"unique-tok-{time.time_ns()}"  # unique per test to avoid cross-test pollution
    sig = _sign(key="k", timestamp=ts, token=tok)
    payload = {
        "timestamp": ts,
        "token": tok,
        "signature": sig,
        "recipient": "in_abc@ex.com",
    }
    with patch("src.app.core.email.mailgun.tasks.process_mailgun_inbound.delay"):
        r1 = await layered_client.post(
            "/api/v1/webhooks/mailgun/inbound", data=payload
        )
        r2 = await layered_client.post(
            "/api/v1/webhooks/mailgun/inbound", data=payload
        )
    assert r1.status_code == 200
    assert r2.status_code == 401
    assert "replay" in r2.json()["error"].lower()


@pytest.mark.asyncio
async def test_webhook_returns_200_even_when_broker_refuses_enqueue(
    layered_client, monkeypatch, tmp_path
):
    """Broker down after our 200 → sweeper picks up later. The
    webhook itself must not 5xx (Mailgun would retry-storm)."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    ts = str(int(time.time()))
    tok = f"broker-down-tok-{time.time_ns()}"
    sig = _sign(key="k", timestamp=ts, token=tok)

    with patch(
        "src.app.core.email.mailgun.tasks.process_mailgun_inbound.delay",
        side_effect=RuntimeError("broker down"),
    ):
        resp = await layered_client.post(
            "/api/v1/webhooks/mailgun/inbound",
            data={
                "timestamp": ts,
                "token": tok,
                "signature": sig,
                "recipient": "in_abc@ex.com",
            },
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Health endpoint — no auth, no signature
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok_no_auth(layered_client, monkeypatch):
    monkeypatch.setenv("MAILGUN_DOMAIN", "sandbox-test.mailgun.org")
    resp = await layered_client.get("/api/v1/webhooks/mailgun/inbound/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["domain"] == "sandbox-test.mailgun.org"


@pytest.mark.asyncio
async def test_health_endpoint_returns_null_domain_when_unset(
    layered_client, monkeypatch
):
    monkeypatch.delenv("MAILGUN_DOMAIN", raising=False)
    resp = await layered_client.get("/api/v1/webhooks/mailgun/inbound/health")
    assert resp.status_code == 200
    assert resp.json()["domain"] is None
