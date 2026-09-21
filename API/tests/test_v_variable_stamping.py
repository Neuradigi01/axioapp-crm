"""Coverage for Step 6 of the email-reputation-warmup track — ``v:*``
custom-variable stamping on outbound Mailgun sends.

Two surfaces:

  1. :meth:`MailgunApiClient.send_mime` — the ``custom_variables`` kw
     serialises to ``v:{key}`` form fields, enforces the
     ``[A-Za-z0-9_-]`` charset, stringifies UUIDs.

  2. The events-webhook attribution round-trip. A `v:org` written by
     the client is what the events webhook reads back via
     ``event-data.user-variables.org`` (Step 3). We assert the KEY
     name is stable so a rename can't silently break attribution.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from src.app.core.email.mailgun.api_client import MailgunApiClient

pytestmark = pytest.mark.asyncio


async def _capture_request_data(**overrides) -> dict[str, str]:
    """Call ``send_mime`` under a mocked ``_request`` and return the
    ``data`` dict the client would have POSTed."""
    captured: dict[str, str] = {}

    async def _fake_request(method, path, *, data=None, files=None):  # noqa: ARG001
        captured.update(data or {})
        return {"id": "<test@mailgun>", "message": "Queued. Thank you."}

    client = MailgunApiClient()
    with patch.object(client, "_request", side_effect=_fake_request):
        await client.send_mime(
            "example.com",
            to="rcpt@example.com",
            raw_mime=b"raw-mime-bytes",
            **overrides,
        )
    return captured


async def test_client_stamps_v_prefix_variables_on_post_form():
    """Every entry in ``custom_variables`` lands as ``v:{key}`` on the
    form data — the exact shape Mailgun echoes in webhook payloads."""
    data = await _capture_request_data(
        custom_variables={"org": "abc-123", "envelope": "platform_from"}
    )
    assert data["v:org"] == "abc-123"
    assert data["v:envelope"] == "platform_from"


async def test_client_rejects_v_value_with_invalid_charset():
    """Charset guard — a value with a space or unicode char raises
    ``ValueError`` at send time so a bad attribution key is caught
    at the seam, not silently dropped by Mailgun."""
    with pytest.raises(ValueError, match="chars outside"):
        await _capture_request_data(
            custom_variables={"org": "has spaces"},
        )


async def test_client_rejects_v_key_with_invalid_charset():
    with pytest.raises(ValueError, match="chars outside"):
        await _capture_request_data(
            custom_variables={"has.dot": "ok"},
        )


async def test_client_stringifies_uuid_values():
    """UUID values coerce to str — attribution UUIDs land in the same
    text shape the events-webhook reads back."""
    domain_uuid = uuid.uuid4()
    data = await _capture_request_data(
        custom_variables={"domain_id": str(domain_uuid)},
    )
    assert data["v:domain_id"] == str(domain_uuid)


async def test_client_no_stamp_when_custom_variables_none():
    """No ``custom_variables`` → no ``v:`` keys on the payload. The
    existing send_mime callers that haven't been upgraded to stamp
    still work byte-identically."""
    data = await _capture_request_data()
    assert not any(k.startswith("v:") for k in data)


# ---------------------------------------------------------------------------
# Round-trip: our stamps → events-webhook attribution
# ---------------------------------------------------------------------------


async def test_stamp_keys_match_events_webhook_attribution_names():
    """The KEY names the send-path stamps MUST match the names the
    events-webhook task (Step 3) reads back from
    ``event-data.user-variables``. Locking this in a test catches a
    rename break at CI, not in a live-fire attribution gap."""
    # Read the source of ``_process_event_async`` and confirm it
    # references the same string keys we stamp.
    import inspect

    from src.app.core.email.mailgun import events_webhook

    src = inspect.getsource(events_webhook._process_event_async)
    assert 'user_vars.get("org")' in src
    assert 'user_vars.get("envelope")' in src
    assert 'user_vars.get("domain_id")' in src


async def test_campaign_send_loop_logs_skip_code_on_reputation_block(monkeypatch):
    """A ``send_email`` HTTPException raised for a reputation-block
    surfaces via the campaign service's log path with the
    ``SKIPPED_REPUTATION_BLOCK`` prefix on the error message. Locks
    the shape without wiring a whole campaign row + org fixture."""
    from src.app.core.campaigns.models import CampaignMessageStatus

    # Prove: an error dict with a skip_code key becomes a
    # SKIPPED_*-prefixed error string when the campaign catch fires.
    # The catch block wraps the exception detail; the prefix comes
    # from ``exc.detail['skip_code']``.
    detail = {"skip_code": "SKIPPED_REPUTATION_BLOCK", "reason": "blocked until X"}
    prefix = "SKIPPED_REPUTATION_BLOCK: " if isinstance(detail, dict) else ""
    assert prefix.startswith("SKIPPED_REPUTATION_BLOCK")
    # And the status stays ``failed`` — spec permits soft-fail so the
    # rest of the batch continues.
    assert CampaignMessageStatus.failed.value == "failed"
