"""Action-node tests — pure Python, no live network / DB.

Covers registration + SSRF blocklist + validation + JSONPath
extractor. Full DB-bound tests (write via save_target, tag idempotency,
delay+sweeper resume, api_request end-to-end against a mock server)
land in ``test_action_nodes_db.py`` — deferred to batch pytest per
memory ``feedback_pause_before_pytest.md``.
"""

from __future__ import annotations

import ipaddress
import uuid
from types import SimpleNamespace

import pytest

from src.app.core.chatbots.engine import NODE_REGISTRY
from src.app.core.chatbots.http_client_safe import (
    UnsafeUrl,
    _is_private_or_reserved_ip,
    _validate_url,
)
from src.app.core.chatbots.nodes.api_request import (
    _apply_captures,
    _redact_headers,
)


# --- Registry side-effect --------------------------------------------------


def test_all_step9_nodes_registered() -> None:
    for t in ("condition", "delay", "add_tag", "set_custom_field", "api_request"):
        assert t in NODE_REGISTRY, f"node '{t}' not registered"


# --- SSRF gates -----------------------------------------------------------


@pytest.mark.parametrize(
    "ip_str",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",   # AWS/GCP metadata
        "0.0.0.0",
        "224.0.0.1",         # multicast
        "::1",
        "fe80::1",
        "fd00::1",           # IPv6 ULA
        "::ffff:127.0.0.1",  # IPv4-mapped IPv6 loopback
    ],
)
def test_private_and_reserved_ips_rejected(ip_str: str) -> None:
    ip = ipaddress.ip_address(ip_str)
    assert _is_private_or_reserved_ip(ip) is True, f"{ip_str} should be blocked"


@pytest.mark.parametrize(
    "ip_str",
    [
        "8.8.8.8",           # Google DNS
        "1.1.1.1",           # Cloudflare DNS
        "104.16.132.229",    # Cloudflare edge
        "140.82.113.4",      # GitHub
        "2606:4700::1111",   # Cloudflare IPv6
    ],
)
def test_public_ips_allowed(ip_str: str) -> None:
    ip = ipaddress.ip_address(ip_str)
    assert _is_private_or_reserved_ip(ip) is False, f"{ip_str} should be allowed"


def test_http_scheme_rejected() -> None:
    with pytest.raises(UnsafeUrl, match="HTTPS only"):
        _validate_url("http://example.com")


def test_ftp_scheme_rejected() -> None:
    with pytest.raises(UnsafeUrl):
        _validate_url("ftp://example.com/file")


def test_missing_host_rejected() -> None:
    with pytest.raises(UnsafeUrl, match="missing host"):
        _validate_url("https:///path")


def test_raw_ip_url_pointing_at_private_range_rejected() -> None:
    """Attacker can't dodge DNS by embedding a private IP directly
    in the URL."""
    with pytest.raises(UnsafeUrl, match="private/reserved IP"):
        _validate_url("https://127.0.0.1/")
    with pytest.raises(UnsafeUrl, match="private/reserved IP"):
        _validate_url("https://169.254.169.254/latest/meta-data/")


def test_public_https_url_passes_pre_dns_gate() -> None:
    scheme, host, port = _validate_url("https://api.github.com/zen")
    assert scheme == "https"
    assert host == "api.github.com"
    assert port == 443


# --- api_request helpers --------------------------------------------------


def test_apply_captures_simple_dot_path() -> None:
    data = {"user": {"name": "Alex", "score": 87}}
    spec = {"name": "$.user.name", "score": "$.user.score"}
    assert _apply_captures(spec, data) == {"name": "Alex", "score": 87}


def test_apply_captures_missing_path_returns_none() -> None:
    data = {"user": {"name": "Alex"}}
    spec = {"missing": "$.user.email"}
    assert _apply_captures(spec, data) == {"missing": None}


def test_apply_captures_empty_spec_returns_empty() -> None:
    assert _apply_captures({}, {"any": "data"}) == {}
    assert _apply_captures({"a": "$.a"}, None) == {}


def test_redact_headers_hides_auth_tokens() -> None:
    hdrs = {
        "Authorization": "Bearer sk-abc123",
        "Cookie": "session=deadbeef",
        "X-Api-Key": "abc",
        "Content-Type": "application/json",
    }
    redacted = _redact_headers(hdrs)
    assert redacted["Authorization"] == "***redacted***"
    assert redacted["Cookie"] == "***redacted***"
    assert redacted["X-Api-Key"] == "***redacted***"
    assert redacted["Content-Type"] == "application/json"


# --- Handler-level rejections --------------------------------------------


@pytest.mark.asyncio
async def test_condition_rejects_missing_ast() -> None:
    from src.app.core.chatbots.nodes.condition import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=None, lead_id=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="c1",
        node_type="condition",
        node_config={},
        run_context={"answers": {}},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "AST" in result.error or "condition" in result.error


@pytest.mark.asyncio
async def test_delay_rejects_missing_duration() -> None:
    from src.app.core.chatbots.nodes.delay import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=None, lead_id=None,
            next_step_at=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="d1",
        node_type="delay",
        node_config={},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "duration" in result.error.lower()


@pytest.mark.asyncio
async def test_delay_rejects_over_30_days() -> None:
    from src.app.core.chatbots.nodes.delay import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=None, lead_id=None,
            next_step_at=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="d1",
        node_type="delay",
        node_config={"amount": 40, "unit": "days"},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "rejected" in result.error.lower()


@pytest.mark.asyncio
async def test_delay_parks_with_correct_key() -> None:
    from src.app.core.chatbots.nodes.delay import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=None, lead_id=None,
            next_step_at=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="d1",
        node_type="delay",
        node_config={"duration_seconds": 300},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.park_key == ("delay", "d1")
    assert result.output["delayed_seconds"] == 300
    # next_step_at is stamped on the fake run object.
    assert fake_ctx.run.next_step_at is not None


@pytest.mark.asyncio
async def test_delay_resumed_advances_via_default_edge() -> None:
    from src.app.core.chatbots.nodes.delay import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=None, lead_id=None,
            next_step_at=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="d1",
        node_type="delay",
        node_config={"duration_seconds": 300},
        run_context={"resumed_from_park": True, "resumed_by": "delay_expired"},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.next_edge_label is None  # default edge
    assert result.context_patch == {"resumed_from_park": False}
    assert result.park_key is None
    assert result.error is None


@pytest.mark.asyncio
async def test_add_tag_rejects_lead_entity() -> None:
    from src.app.core.chatbots.nodes.add_tag import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=uuid.uuid4(), lead_id=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="t1",
        node_type="add_tag",
        node_config={"entity": "lead", "tags": ["hot"]},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "contact" in result.error


@pytest.mark.asyncio
async def test_add_tag_rejects_invalid_operation() -> None:
    from src.app.core.chatbots.nodes.add_tag import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=uuid.uuid4(), lead_id=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="t1",
        node_type="add_tag",
        node_config={"operation": "invert", "tags": ["hot"]},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "add|remove" in result.error


@pytest.mark.asyncio
async def test_api_request_rejects_bad_method() -> None:
    from src.app.core.chatbots.nodes.api_request import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=None, lead_id=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="a1",
        node_type="api_request",
        node_config={"method": "TRACE", "url": "https://example.com"},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "method" in result.error.lower()


@pytest.mark.asyncio
async def test_api_request_rejects_missing_url() -> None:
    from src.app.core.chatbots.nodes.api_request import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=None, lead_id=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="a1",
        node_type="api_request",
        node_config={"method": "GET"},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "url" in result.error.lower()


@pytest.mark.asyncio
async def test_set_custom_field_rejects_missing_target() -> None:
    from src.app.core.chatbots.nodes.set_custom_field import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            conversation_id=None, contact_id=None, lead_id=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="s1",
        node_type="set_custom_field",
        node_config={"value": "hi"},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "save_to" in result.error


# --- Sweeper task exists --------------------------------------------------


def test_sweep_chatbot_waits_task_exists() -> None:
    """Guardrail — celery beat entry references this name."""
    from src.app.core.chatbots.tasks import sweep_chatbot_waits

    assert callable(sweep_chatbot_waits)
