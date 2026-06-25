"""Variable engine tests.

Covers the parser (``extract_variable_paths``), the strict renderer
(``render`` — raises on missing), the lenient resolver (``resolve`` —
empty on missing), the Jinja-statement rejector, and the per-channel
variable picker registry. No DB / network — pure functions.
"""
from __future__ import annotations

import pytest

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.variables import (
    ALLOWED_VARIABLES_BY_CHANNEL,
    MissingVariable,
    TemplateSyntaxError,
    VariableDef,
    extract_variable_paths,
    extract_variables,
    reject_jinja_statements,
    render,
    resolve,
    variables_for_channel,
)


# --- extract_variables / extract_variable_paths ------------------------


def test_extract_finds_all_dot_paths():
    text = "Hi {{ contact.first_name }}, your order {{ order.id }} ships from {{ org.name }}."
    assert extract_variable_paths(text) == [
        "contact.first_name",
        "order.id",
        "org.name",
    ]


def test_extract_deduplicates_and_sorts():
    text = "{{ contact.name }} {{ org.name }} {{ contact.name }}"
    assert extract_variable_paths(text) == ["contact.name", "org.name"]


def test_extract_alias_returns_same_result():
    text = "Hi {{ contact.first_name }}!"
    assert extract_variables(text) == extract_variable_paths(text)


def test_extract_empty_returns_empty():
    assert extract_variable_paths("") == []
    assert extract_variable_paths(None) == []  # type: ignore[arg-type]


def test_extract_ignores_stray_braces():
    # A single `{` shouldn't get eaten; spec says `{{a.b}}` shape only.
    assert extract_variable_paths("price is {currency}{{ amount }}") == ["amount"]


def test_extract_ignores_unsupported_path_shape():
    # `{{Contact.first_name}}` (uppercase) and `{{1.foo}}` aren't valid.
    assert extract_variable_paths("{{Contact.first_name}} {{1.foo}}") == []


# --- reject_jinja_statements -------------------------------------------


def test_jinja_if_statement_rejected():
    with pytest.raises(TemplateSyntaxError, match="`{% ... %}`"):
        reject_jinja_statements("Hello {% if user %}{{user.name}}{% endif %}")


def test_jinja_comment_rejected():
    with pytest.raises(TemplateSyntaxError, match="`{# ... #}`"):
        reject_jinja_statements("Hello {# secret comment #} world")


def test_plain_template_accepted():
    reject_jinja_statements("Hi {{ contact.first_name }}!")  # no raise


# --- render (strict) ---------------------------------------------------


def test_render_substitutes_known_paths():
    out = render(
        "Hi {{ contact.first_name }} from {{ org.name }}",
        {"contact": {"first_name": "Asha"}, "org": {"name": "Acme"}},
    )
    assert out == "Hi Asha from Acme"


def test_render_raises_missing_variable_with_all_paths():
    with pytest.raises(MissingVariable) as info:
        render(
            "{{ contact.first_name }} / {{ lead.score }} / {{ org.name }}",
            {"contact": {"first_name": "Asha"}},
        )
    assert info.value.paths == ["lead.score", "org.name"]


def test_render_html_escapes_by_default():
    out = render(
        "Hi {{ contact.first_name }}",
        {"contact": {"first_name": "<script>"}},
    )
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_render_autoescape_off_emits_raw():
    out = render(
        "Hi {{ contact.first_name }}",
        {"contact": {"first_name": "<b>Asha</b>"}},
        autoescape=False,
    )
    assert out == "Hi <b>Asha</b>"


def test_render_none_value_becomes_empty():
    out = render(
        "Last name: {{ contact.last_name }}.",
        {"contact": {"last_name": None}},
    )
    assert out == "Last name: ."


def test_render_bool_becomes_lowercase_string():
    out = render(
        "VIP: {{ contact.is_vip }}",
        {"contact": {"is_vip": True}},
    )
    assert out == "VIP: true"


def test_render_rejects_jinja_statements():
    with pytest.raises(TemplateSyntaxError):
        render("Hi {% if x %}A{% endif %}", {})


# --- resolve (lenient) -------------------------------------------------


def test_resolve_missing_becomes_empty_not_token():
    out = resolve(
        "Hi {{ contact.first_name }} {{ lead.score }}",
        {"contact": {"first_name": "Asha"}},
    )
    assert out == "Hi Asha "
    # Confirm the missing path doesn't leak the literal `{{lead.score}}`.
    assert "{{" not in out
    assert "}}" not in out


def test_resolve_xss_safe_by_default():
    out = resolve(
        "Note: {{ contact.note }}",
        {"contact": {"note": "<script>alert(1)</script>"}},
    )
    assert "<script" not in out


def test_resolve_rejects_jinja_statements():
    with pytest.raises(TemplateSyntaxError):
        resolve("Hi {% if x %}A{% endif %}", {})


# --- variables_for_channel + registry ----------------------------------


def test_registry_has_entry_for_every_supported_channel():
    # Channels in scope at module-launch (Step 1 spec).
    for ch in (
        ConversationChannel.email,
        ConversationChannel.whatsapp,
        ConversationChannel.sms,
        ConversationChannel.facebook,
        ConversationChannel.instagram,
    ):
        assert ch in ALLOWED_VARIABLES_BY_CHANNEL, ch


def test_variables_for_channel_returns_copy():
    a = variables_for_channel(ConversationChannel.email)
    b = variables_for_channel(ConversationChannel.email)
    assert a == b
    assert a is not b  # caller can mutate without poisoning the registry
    a.append(VariableDef("test.key", "test"))
    assert variables_for_channel(ConversationChannel.email) == b


def test_sms_registry_is_tight():
    # SMS bodies are 160-char; high-cost variables shouldn't surface.
    sms_keys = {v.key for v in variables_for_channel(ConversationChannel.sms)}
    assert "contact.first_name" in sms_keys
    assert "org.name" in sms_keys
    # Heavy / multi-paragraph fields shouldn't be in the SMS picker.
    assert "org.address" not in sms_keys


def test_email_registry_includes_quote_and_invoice_namespaces():
    email_keys = {v.key for v in variables_for_channel(ConversationChannel.email)}
    assert "quote.id" in email_keys
    assert "invoice.id" in email_keys
    assert "sender.signature" in email_keys
