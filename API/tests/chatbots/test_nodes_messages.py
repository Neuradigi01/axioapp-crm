"""Message-node handler tests — pure Python, no DB / live send.

Covers the sync validation + reply-matching paths. Real WA send +
outbound-Message persistence + WA-window / Baileys-fallback flows
land in ``test_nodes_messages_db.py`` — deferred to batch pytest
per memory ``feedback_pause_before_pytest.md``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.app.core.chatbots.channel_bridge import (
    _escape_for_channel,
    _numbered_text_fallback,
    render_variables,
)
from src.app.core.chatbots.engine import NODE_REGISTRY
from src.app.core.chatbots.nodes import _shared


# --- Registry side-effect --------------------------------------------------


def test_all_step7_node_types_registered() -> None:
    """Package import in ``chatbots/__init__.py`` registers each
    handler. Guardrail against a future refactor that forgets one."""
    for t in (
        "text_button",
        "media_button",
        "list",
        "template",
        "catalog_message",
        "single_product",
        "multi_product",
    ):
        assert t in NODE_REGISTRY, f"node '{t}' not registered"


# --- Variable resolver ----------------------------------------------------


def test_render_variables_answers() -> None:
    text = "Hi {{answers.name}}, budget?"
    ctx = {"answers": {"name": "Alex"}, "channel": "whatsapp"}
    assert render_variables(text, run_context=ctx) == "Hi Alex, budget?"


def test_render_variables_contact_field() -> None:
    text = "Hi {{contact.first_name}}"
    ctx = {"answers": {}, "channel": "whatsapp"}
    assert render_variables(text, run_context=ctx, contact_data={"first_name": "Asha"}) == "Hi Asha"


def test_render_variables_run_scope() -> None:
    text = "Channel: {{run.channel}}"
    ctx = {"answers": {}, "channel": "email"}
    assert render_variables(text, run_context=ctx, channel="email") == "Channel: email"


def test_render_variables_missing_renders_empty() -> None:
    text = "Hi {{answers.missing}} bye"
    assert render_variables(text, run_context={"answers": {}}) == "Hi  bye"


def test_render_variables_escapes_html_for_email() -> None:
    """Case M4 — no XSS via customer text in email bodies."""
    text = "Reply from {{answers.name}}"
    ctx = {"answers": {"name": "<script>alert(1)</script>"}}
    rendered = render_variables(text, run_context=ctx, channel="email")
    assert "&lt;script&gt;" in rendered
    assert "<script>" not in rendered


def test_render_variables_strips_control_chars_for_wa() -> None:
    """Case M4 — control characters that would break WA's client UI
    are stripped from ``answers.*`` substitutions."""
    text = "Reply: {{answers.name}}"
    ctx = {"answers": {"name": "hi\x00\x01there"}}
    rendered = render_variables(text, run_context=ctx, channel="whatsapp")
    assert "\x00" not in rendered
    assert "\x01" not in rendered
    assert "hi" in rendered
    assert "there" in rendered


def test_escape_for_channel_preserves_wa_newlines() -> None:
    assert "\n" in _escape_for_channel("line1\nline2", channel="whatsapp")
    assert "\t" in _escape_for_channel("col1\tcol2", channel="whatsapp")


# --- Numbered-text Baileys fallback ---------------------------------------


def test_numbered_fallback_shape() -> None:
    body = "Pick one"
    options = [
        {"id": "a", "title": "Yes"},
        {"id": "b", "title": "No"},
    ]
    rendered = _numbered_text_fallback(body, options)
    assert rendered == "Pick one\n\nReply 1 for Yes\nReply 2 for No"


# --- Button-reply matcher -------------------------------------------------


def test_match_button_reply_exact_title() -> None:
    buttons = [{"id": "yes", "title": "Yes"}, {"id": "no", "title": "No"}]
    assert _shared.match_button_reply("yes", buttons) == "yes"
    assert _shared.match_button_reply("YES", buttons) == "yes"
    assert _shared.match_button_reply("No", buttons) == "no"


def test_match_button_reply_prefix() -> None:
    buttons = [{"id": "yes", "title": "Yes"}]
    assert _shared.match_button_reply("Yes I do", buttons) == "yes"


def test_match_button_reply_numbered_fallback() -> None:
    buttons = [
        {"id": "a", "title": "Alpha"},
        {"id": "b", "title": "Beta"},
        {"id": "c", "title": "Gamma"},
    ]
    assert _shared.match_button_reply("1", buttons) == "a"
    assert _shared.match_button_reply("2.", buttons) == "b"
    assert _shared.match_button_reply("Reply 3", buttons) == "c"


def test_match_button_reply_no_match_returns_none() -> None:
    buttons = [{"id": "yes", "title": "Yes"}]
    assert _shared.match_button_reply("maybe", buttons) is None
    assert _shared.match_button_reply("", buttons) is None
    assert _shared.match_button_reply("99", buttons) is None


# --- Resume-from-park flag helpers ---------------------------------------


def test_is_resumed_flag_reads_context() -> None:
    ctx = SimpleNamespace(run_context={"resumed_from_park": True})
    assert _shared.is_resumed_from_park(ctx) is True

    ctx2 = SimpleNamespace(run_context={"resumed_from_park": False})
    assert _shared.is_resumed_from_park(ctx2) is False

    ctx3 = SimpleNamespace(run_context={})
    assert _shared.is_resumed_from_park(ctx3) is False


def test_clear_resume_flag_returns_patch() -> None:
    assert _shared.clear_resume_flag() == {"resumed_from_park": False}


# --- Stub handlers --------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node_type",
    ["catalog_message", "single_product", "multi_product"],
)
async def test_commerce_stubs_return_errored(node_type: str) -> None:
    """v1 stubs error cleanly so operators see the empty-state
    reason. Real handlers land with a future WA Commerce track."""
    handler = NODE_REGISTRY[node_type]
    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(id=uuid.uuid4()),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="n1",
        node_type=node_type,
        node_config={},
        run_context={},
        is_test=True,
    )
    result = await handler(fake_ctx)
    assert result.error is not None
    assert "Commerce" in result.error or "commerce" in result.error


# --- Config validation (handler-level) -----------------------------------


@pytest.mark.asyncio
async def test_text_button_rejects_missing_body() -> None:
    from src.app.core.chatbots.nodes.text_button import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(id=uuid.uuid4(), conversation_id=None, contact_id=None),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="n1",
        node_type="text_button",
        node_config={"buttons": [{"id": "a", "title": "A"}]},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "body" in result.error.lower()


@pytest.mark.asyncio
async def test_text_button_rejects_too_many_buttons() -> None:
    from src.app.core.chatbots.nodes.text_button import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(id=uuid.uuid4(), conversation_id=None, contact_id=None),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="n1",
        node_type="text_button",
        node_config={
            "body": "hi",
            "buttons": [{"id": f"b{i}", "title": f"B{i}"} for i in range(4)],
        },
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "1-3" in result.error


@pytest.mark.asyncio
async def test_text_button_rejects_body_over_1024_chars() -> None:
    from src.app.core.chatbots.nodes.text_button import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(id=uuid.uuid4(), conversation_id=None, contact_id=None),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="n1",
        node_type="text_button",
        node_config={
            "body": "x" * 1025,
            "buttons": [{"id": "a", "title": "A"}],
        },
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "1024" in result.error


@pytest.mark.asyncio
async def test_list_rejects_over_10_rows() -> None:
    from src.app.core.chatbots.nodes.list import handle

    sections = [
        {
            "title": "sec",
            "rows": [
                {"id": f"r{i}", "title": f"R{i}"} for i in range(11)
            ],
        }
    ]
    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(id=uuid.uuid4(), conversation_id=None, contact_id=None),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="n1",
        node_type="list",
        node_config={"body": "pick", "sections": sections},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "10" in result.error


@pytest.mark.asyncio
async def test_template_rejects_missing_id() -> None:
    from src.app.core.chatbots.nodes.template import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(id=uuid.uuid4(), conversation_id=None, contact_id=None),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="n1",
        node_type="template",
        node_config={"variables": {}},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "template_id" in result.error


@pytest.mark.asyncio
async def test_template_rejects_bad_uuid() -> None:
    from src.app.core.chatbots.nodes.template import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(id=uuid.uuid4(), conversation_id=None, contact_id=None),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="n1",
        node_type="template",
        node_config={"template_id": "not-a-uuid", "variables": {}},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "UUID" in result.error
