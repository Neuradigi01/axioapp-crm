"""Unit tests for the WhatsApp named-variable auto-resolution used by
the campaign dispatcher.

The dispatcher reads named CRM variables (``{{contact.first_name}}``,
``{{org.name}}``) off the template and resolves each against the
recipient's contact + the org before shipping positional parameters to
Meta. The failure this file pins is:

  * ``tbl_whatsapp_templates.body`` gets overwritten by Meta's sync
    with the positional copy (``{{1}} {{2}}``), so re-parsing it
    recovers no names.
  * The pre-fix resolver read ``body`` and returned an empty dict,
    causing Meta to reject with ``132000 — number of localizable_
    params (0) does not match the expected number of params (N)``.

Post-fix the resolver reads either the pre-conversion ``body_components``
(preferred — same row, no extra query) or a caller-supplied
``named_body_override`` (the central-library ``body_text`` fetched once
per chunk). Tests here run purely in-memory with SimpleNamespace stubs
— no DB, no fixtures, so they're fast to run standalone.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.app.core.campaigns.service import (
    _extract_named_body_from_components,
    _resolve_named_wa_variables,
)


def _fake_template(*, body: str, body_components: list | None) -> SimpleNamespace:
    """A minimal stand-in for ``WhatsAppTemplate``. Only the fields the
    resolver reads are stubbed."""
    return SimpleNamespace(body=body, body_components=body_components)


def _fake_contact(full_name: str = "Ajay Kumar", email: str = "a@x.com") -> SimpleNamespace:
    return SimpleNamespace(
        id="c-1",
        full_name=full_name,
        email=email,
        phone="+919999",
        source="manual",
        custom_data={},
    )


def _fake_org(name: str = "Ajay's Workspace") -> SimpleNamespace:
    return SimpleNamespace(name=name, support_email="s@x.com")


# ---------------------------------------------------------------------------
# _extract_named_body_from_components
# ---------------------------------------------------------------------------


def test_extract_named_body_returns_body_component_text():
    template = _fake_template(
        body="Hi {{1}}",
        body_components=[
            {"type": "HEADER", "format": "TEXT", "text": "Header"},
            {"type": "BODY", "text": "Hi {{contact.first_name}}"},
            {"type": "FOOTER", "text": "Static footer"},
        ],
    )
    assert _extract_named_body_from_components(template) == "Hi {{contact.first_name}}"


def test_extract_named_body_returns_none_when_components_missing():
    template = _fake_template(body="Hi {{1}}", body_components=None)
    assert _extract_named_body_from_components(template) is None


def test_extract_named_body_returns_none_when_body_component_absent():
    """Templates with only header+footer (no body) should return None
    so the caller falls back to the central-library source."""
    template = _fake_template(
        body="",
        body_components=[
            {"type": "HEADER", "text": "Header"},
            {"type": "FOOTER", "text": "Footer"},
        ],
    )
    assert _extract_named_body_from_components(template) is None


def test_extract_named_body_case_insensitive_type_matching():
    """Meta echoes lowercase component types occasionally; the
    extraction must not be brittle to case."""
    template = _fake_template(
        body="Hi {{1}}",
        body_components=[{"type": "body", "text": "Hi {{contact.first_name}}"}],
    )
    assert _extract_named_body_from_components(template) == "Hi {{contact.first_name}}"


# ---------------------------------------------------------------------------
# _resolve_named_wa_variables — the primary bug fix
# ---------------------------------------------------------------------------


def test_resolves_from_body_components_when_meta_body_is_positional():
    """Regression pin: pre-fix, this returned {} because ``body`` had
    already been overwritten to the positional form. Post-fix it reads
    body_components and resolves against the contact + org."""
    template = _fake_template(
        body="Hi {{1}}, from {{2}}",
        body_components=[{"type": "BODY", "text": "Hi {{contact.first_name}}, from {{org.name}}"}],
    )
    result = _resolve_named_wa_variables(template, _fake_contact(), _fake_org())
    assert result == {1: "Ajay", 2: "Ajay's Workspace"}


def test_uses_override_when_supplied_even_if_body_components_present():
    """The caller-supplied override (central library ``body_text``)
    wins over ``body_components`` when both are available. Lets the
    caller migrate to a single source of truth without touching this
    function."""
    template = _fake_template(
        body="Hi {{1}}",
        body_components=[{"type": "BODY", "text": "Different old body {{contact.email}}"}],
    )
    result = _resolve_named_wa_variables(
        template,
        _fake_contact(),
        _fake_org(),
        named_body_override="Hi {{contact.first_name}}",
    )
    assert result == {1: "Ajay"}


def test_falls_back_to_override_when_body_components_missing():
    """Old sync rows from before the body_components column was
    populated have body_components=None. The central-library override
    keeps them working."""
    template = _fake_template(body="Hi {{1}}", body_components=None)
    result = _resolve_named_wa_variables(
        template,
        _fake_contact(),
        _fake_org(),
        named_body_override="Hi {{contact.first_name}} from {{org.name}}",
    )
    assert result == {1: "Ajay", 2: "Ajay's Workspace"}


def test_empty_dict_when_no_source_has_named_body():
    """Both sources exhausted → resolver returns {}. Dispatcher then
    ships whatever the operator supplied via ``template_variables``
    (which may itself be empty for pure-static templates)."""
    template = _fake_template(body="Hello static", body_components=[])
    result = _resolve_named_wa_variables(template, _fake_contact(), _fake_org())
    assert result == {}


def test_empty_dict_when_body_has_no_vars():
    """Vars-free templates return {} — no params to send to Meta,
    which matches Meta's expectations for a static template."""
    template = _fake_template(
        body="Static text no vars",
        body_components=[{"type": "BODY", "text": "Static text no vars"}],
    )
    result = _resolve_named_wa_variables(template, _fake_contact(), _fake_org())
    assert result == {}


def test_repeated_variable_uses_same_positional_slot():
    """Meta collapses repeated vars into one positional slot (matches
    ``convert_to_positional``'s ``seen`` dict). Resolver must agree."""
    template = _fake_template(
        body="{{1}} {{2}} {{1}}",
        body_components=[
            {
                "type": "BODY",
                "text": "{{contact.first_name}} {{org.name}} {{contact.first_name}}",
            }
        ],
    )
    result = _resolve_named_wa_variables(template, _fake_contact(), _fake_org())
    assert result == {1: "Ajay", 2: "Ajay's Workspace"}


def test_falls_back_to_placeholder_for_empty_field():
    """Meta rejects empty positional params. The resolver stamps the
    ``_TEMPLATE_FIELD_FALLBACK`` sentinel (``"Customer"``) so a contact
    with no first_name still ships something Meta will accept."""
    template = _fake_template(
        body="Hi {{1}}",
        body_components=[{"type": "BODY", "text": "Hi {{contact.first_name}}"}],
    )
    contact = _fake_contact(full_name="")  # no first name derivable
    result = _resolve_named_wa_variables(template, contact, _fake_org())
    assert result[1] == "Customer"


def test_unknown_named_path_still_falls_back_to_placeholder():
    """Custom paths the auto-resolver doesn't know about (e.g.
    ``{{promo.code}}``) get the placeholder — the operator can then
    override via ``template_variables`` on the campaign row without
    Meta rejecting the send outright."""
    template = _fake_template(
        body="Code: {{1}}",
        body_components=[{"type": "BODY", "text": "Code: {{promo.code}}"}],
    )
    result = _resolve_named_wa_variables(template, _fake_contact(), _fake_org())
    assert result == {1: "Customer"}


@pytest.mark.parametrize(
    "org_value, expected",
    [
        (_fake_org(name="Acme Inc"), "Acme Inc"),
        (None, "Customer"),  # no org → empty string → fallback placeholder
    ],
)
def test_org_variable_gracefully_handles_missing_org(org_value, expected):
    """``org`` may be None in exotic dispatch paths (e.g. platform-
    internal sends before an org row exists). The resolver must not
    crash and must still ship a non-empty param."""
    template = _fake_template(
        body="From {{1}}",
        body_components=[{"type": "BODY", "text": "From {{org.name}}"}],
    )
    result = _resolve_named_wa_variables(template, _fake_contact(), org_value)
    assert result == {1: expected}
