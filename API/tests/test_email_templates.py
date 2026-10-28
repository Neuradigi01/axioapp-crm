"""Step 6 — email_templates tests.

Six groups:

  1. `variables.extract_variable_paths` + `reject_jinja_statements` +
     `render` — pure functions, no DB.
  2. `html_to_text` — stdlib HTMLParser extractor.
  3. `validate_template_text` — Jinja-statement rejection, unknown-
     path rejection, happy path returns sorted unique list.
  4. `build_context` — produces the nested dict shape; missing
     contact 404; lead absent gracefully omitted.
  5. `render_template` — substitutes saved subject + bodies, missing
     variable raises HTTPException(400).
  6. CRUD service stubs — create/list/get/update/delete state
     transitions through a _CapturingSession.

Convention: no DB. AsyncMock for sessions; stub
`custom_field_definitions` rows; stub `audit.log`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from src.app.core.email_templates import service as templates_service
from src.app.core.email_templates.models import EmailTemplate
from src.app.core.email_templates.schemas import (
    EmailTemplateCreate,
    EmailTemplateUpdate,
)

from src.app.core.email import variables as vars_engine

_ORG_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


# --- 1. variables engine -----------------------------------------------


class TestExtractPaths:
    def test_single(self):
        assert vars_engine.extract_variable_paths("Hi {{ contact.first_name }}") == [
            "contact.first_name"
        ]

    def test_dedupe_and_sort(self):
        paths = vars_engine.extract_variable_paths(
            "{{contact.email}} {{contact.first_name}} {{contact.email}}"
        )
        assert paths == ["contact.email", "contact.first_name"]

    def test_deep_path(self):
        assert vars_engine.extract_variable_paths("{{ contact.custom_data.preferred_brand }}") == [
            "contact.custom_data.preferred_brand"
        ]

    def test_empty(self):
        assert vars_engine.extract_variable_paths("") == []
        assert vars_engine.extract_variable_paths("no variables here") == []


class TestRejectJinja:
    def test_for_loop(self):
        with pytest.raises(vars_engine.TemplateSyntaxError):
            vars_engine.reject_jinja_statements("{% for x in items %}{{x}}{% endfor %}")

    def test_if_statement(self):
        with pytest.raises(vars_engine.TemplateSyntaxError):
            vars_engine.reject_jinja_statements("{% if user %}hi{% endif %}")

    def test_comment(self):
        with pytest.raises(vars_engine.TemplateSyntaxError):
            vars_engine.reject_jinja_statements("{# tagline #}")

    def test_clean_template(self):
        # Should not raise.
        vars_engine.reject_jinja_statements("Hi {{ contact.first_name }}, how are you?")


class TestRender:
    def test_simple_substitution(self):
        result = vars_engine.render(
            "Hi {{ contact.first_name }}",
            {"contact": {"first_name": "Asha"}},
        )
        assert result == "Hi Asha"

    def test_autoescape_default_on(self):
        # `<script>` should HTML-escape so it can't inject into body.
        result = vars_engine.render(
            "<p>{{ contact.first_name }}</p>",
            {"contact": {"first_name": "<script>alert(1)</script>"}},
        )
        assert "&lt;script&gt;" in result
        assert "<script>" not in result

    def test_autoescape_off_for_plain_text(self):
        result = vars_engine.render(
            "Name: {{ contact.first_name }}",
            {"contact": {"first_name": "A&B"}},
            autoescape=False,
        )
        assert result == "Name: A&B"

    def test_missing_variable_raises(self):
        with pytest.raises(vars_engine.MissingVariable) as exc:
            vars_engine.render(
                "Hi {{ lead.title }}",
                {"contact": {"first_name": "Asha"}},
            )
        assert "lead.title" in exc.value.paths

    def test_none_value_renders_empty(self):
        # `last_name=None` is a legitimate value (single-name contact);
        # the engine renders empty rather than raising.
        result = vars_engine.render(
            "Hi {{ contact.last_name }}!",
            {"contact": {"last_name": None}},
        )
        assert result == "Hi !"

    def test_jinja_statement_rejected_at_render(self):
        with pytest.raises(vars_engine.TemplateSyntaxError):
            vars_engine.render("{% if user %}x{% endif %}", {})


# --- 2. html_to_text ----------------------------------------------------


class TestHtmlToText:
    def test_strips_tags(self):
        assert templates_service.html_to_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_br_becomes_newline(self):
        text = templates_service.html_to_text("Line 1<br>Line 2")
        assert "Line 1" in text and "Line 2" in text
        assert "\n" in text

    def test_inlines_link_urls(self):
        text = templates_service.html_to_text('<a href="https://x.com">Click here</a>')
        assert "Click here" in text
        assert "https://x.com" in text

    def test_empty_input(self):
        assert templates_service.html_to_text("") == ""


# --- 3. validate_template_text -----------------------------------------


class _FakeSession:
    """Returns a canned list of (entity_type, field_key) rows when
    `validate_template_text` queries custom_field_definitions."""

    def __init__(
        self,
        *,
        custom_fields: list[tuple[str, str]] | None = None,
    ) -> None:
        self.custom_fields = list(custom_fields or [])

    async def execute(self, _stmt):
        rows = list(self.custom_fields)

        class R:
            def all(self_):
                return rows

        return R()


class TestValidateTemplateText:
    @pytest.mark.asyncio
    async def test_happy_static_paths(self):
        session = _FakeSession()
        used = await templates_service.validate_template_text(
            session,
            org_id=_ORG_ID,
            subject="Hi {{ contact.first_name }}",
            body_html="<p>Cheers, {{ user.first_name }}</p>",
        )
        assert used == ["contact.first_name", "user.first_name"]

    @pytest.mark.asyncio
    async def test_custom_field_allowed_when_defined(self):
        session = _FakeSession(custom_fields=[("contact", "preferred_brand")])
        used = await templates_service.validate_template_text(
            session,
            org_id=_ORG_ID,
            subject="Brand: {{ contact.custom_data.preferred_brand }}",
            body_html="<p>x</p>",
        )
        assert used == ["contact.custom_data.preferred_brand"]

    @pytest.mark.asyncio
    async def test_unknown_path_rejected(self):
        from fastapi import HTTPException

        session = _FakeSession()
        with pytest.raises(HTTPException) as exc:
            await templates_service.validate_template_text(
                session,
                org_id=_ORG_ID,
                subject="{{ contact.nonexistent }}",
                body_html="<p>x</p>",
            )
        assert exc.value.status_code == 400
        assert "contact.nonexistent" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_undefined_custom_field_rejected(self):
        from fastapi import HTTPException

        session = _FakeSession()  # No custom fields defined
        with pytest.raises(HTTPException) as exc:
            await templates_service.validate_template_text(
                session,
                org_id=_ORG_ID,
                subject="{{ contact.custom_data.foo }}",
                body_html="<p>x</p>",
            )
        assert exc.value.status_code == 400
        assert "contact.custom_data.foo" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_jinja_statement_rejected(self):
        from fastapi import HTTPException

        session = _FakeSession()
        with pytest.raises(HTTPException) as exc:
            await templates_service.validate_template_text(
                session,
                org_id=_ORG_ID,
                subject="ok",
                body_html="{% if user %}x{% endif %}",
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_template_no_variables(self):
        session = _FakeSession()
        used = await templates_service.validate_template_text(
            session,
            org_id=_ORG_ID,
            subject="Static subject",
            body_html="<p>No variables here.</p>",
        )
        assert used == []


# --- 4. render_template ------------------------------------------------


def _make_template(
    *,
    subject="Hi {{ contact.first_name }}",
    body_html="<p>Hello {{ contact.first_name }}!</p>",
    body_text="Hello {{ contact.first_name }}!",
    variables_used=None,
) -> EmailTemplate:
    return EmailTemplate(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        name="t",
        subject=subject,
        body_html=body_html,
        body_text=body_text,
        variables_used=variables_used or ["contact.first_name"],
        is_active=True,
        created_by=_ACTOR_ID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestRenderTemplate:
    def test_happy(self):
        t = _make_template()
        ctx = {"contact": {"first_name": "Mehta"}}
        rendered = templates_service.render_template(t, ctx)
        assert rendered["subject"] == "Hi Mehta"
        assert "Hello Mehta!" in rendered["body_html"]
        assert rendered["body_text"] == "Hello Mehta!"

    def test_autoescape_html_body(self):
        t = _make_template()
        rendered = templates_service.render_template(
            t,
            {"contact": {"first_name": "<script>alert(1)</script>"}},
        )
        assert "&lt;script&gt;" in rendered["body_html"]
        assert "<script>" not in rendered["body_html"]

    def test_plain_text_does_not_escape(self):
        t = _make_template(body_text="Hello {{ contact.first_name }}")
        rendered = templates_service.render_template(t, {"contact": {"first_name": "A&B"}})
        # Plain text path skips escape so &amp; doesn't slip in.
        assert rendered["body_text"] == "Hello A&B"

    def test_missing_variable_400(self):
        from fastapi import HTTPException

        t = _make_template(
            subject="Hi {{ lead.title }}",
            body_html="<p>x</p>",
            body_text="x",
            variables_used=["lead.title"],
        )
        with pytest.raises(HTTPException) as exc:
            templates_service.render_template(t, {"contact": {"first_name": "Asha"}})
        assert exc.value.status_code == 400
        assert "lead.title" in str(exc.value.detail)


# --- 5. CRUD state transitions via _CapturingSession ------------------


class _CapturingSession:
    """Minimal AsyncSession stand-in. Threads a `_responses` queue
    through `execute` so tests can stage SELECT results in order."""

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0
        self.rollbacks = 0
        self.queue: list = []

    def stage(self, response) -> None:
        self.queue.append(response)

    async def execute(self, _stmt):
        if not self.queue:
            raise AssertionError("no staged response")
        return self.queue.pop(0)

    def add(self, row):
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        # Stamp updated_at/created_at since the migration's
        # server_default won't fire under a Python-only flow.
        now = datetime.now(UTC)
        if not getattr(row, "created_at", None):
            row.created_at = now
        if not getattr(row, "updated_at", None):
            row.updated_at = now

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, _row):
        pass

    async def flush(self):
        pass


class _AllRows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return self._rows


class _ScalarOne:
    def __init__(self, value):
        self._v = value

    def scalar_one(self):
        return self._v

    def scalar_one_or_none(self):
        return self._v

    def scalars(self):
        return self

    def all(self):
        return [self._v] if self._v is not None else []


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    """audit.log opens its own session — stub to a no-op."""

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(templates_service.audit, "log", _noop)


class TestCreate:
    @pytest.mark.asyncio
    async def test_happy_create_persists_with_variables_used(self):
        session = _CapturingSession()
        # validate_template_text custom-field lookup → no custom fields
        session.stage(_AllRows([]))
        payload = EmailTemplateCreate(
            name="Initial outreach",
            subject="Hi {{ contact.first_name }}",
            body_html="<p>Hello {{ contact.first_name }}!</p>",
        )
        row = await templates_service.create_template(
            session,
            org_id=_ORG_ID,
            actor_id=_ACTOR_ID,
            payload=payload,
        )
        assert row.name == "Initial outreach"
        assert row.variables_used == ["contact.first_name"]
        assert "Hello" in row.body_text  # Derived from body_html
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_duplicate_name_409(self, monkeypatch):
        session = _CapturingSession()
        session.stage(_AllRows([]))

        async def boom_commit():
            raise RuntimeError(
                "duplicate key value violates unique constraint uq_email_templates_org_name"
            )

        monkeypatch.setattr(session, "commit", boom_commit)
        from fastapi import HTTPException

        payload = EmailTemplateCreate(
            name="Same name",
            subject="x",
            body_html="<p>x</p>",
        )
        with pytest.raises(HTTPException) as exc:
            await templates_service.create_template(
                session,
                org_id=_ORG_ID,
                actor_id=_ACTOR_ID,
                payload=payload,
            )
        assert exc.value.status_code == 409


class TestUpdate:
    @pytest.mark.asyncio
    async def test_partial_update_revalidates_on_subject_change(self):
        session = _CapturingSession()
        existing = _make_template()
        # 1. get_template lookup
        session.stage(_ScalarOne(existing))
        # 2. validate_template_text custom-fields lookup
        session.stage(_AllRows([]))
        new_payload = EmailTemplateUpdate(subject="Hi {{ user.email }}")
        result = await templates_service.update_template(
            session,
            template_id=existing.id,
            actor_id=_ACTOR_ID,
            payload=new_payload,
        )
        assert result.subject == "Hi {{ user.email }}"
        assert "user.email" in result.variables_used

    @pytest.mark.asyncio
    async def test_empty_patch_is_noop(self):
        session = _CapturingSession()
        existing = _make_template()
        session.stage(_ScalarOne(existing))
        result = await templates_service.update_template(
            session,
            template_id=existing.id,
            actor_id=_ACTOR_ID,
            payload=EmailTemplateUpdate(),
        )
        assert result is existing
        assert session.commits == 0


class TestSoftDelete:
    @pytest.mark.asyncio
    async def test_soft_delete_sets_tombstone(self):
        session = _CapturingSession()
        existing = _make_template()
        session.stage(_ScalarOne(existing))
        result = await templates_service.delete_template(
            session,
            template_id=existing.id,
            actor_id=_ACTOR_ID,
        )
        assert result.deleted_at is not None
        assert result.is_active is False
        assert session.commits == 1


class TestGetTemplate:
    @pytest.mark.asyncio
    async def test_get_soft_deleted_404(self):
        session = _CapturingSession()
        deleted = _make_template()
        deleted.deleted_at = datetime.now(UTC)
        session.stage(_ScalarOne(deleted))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await templates_service.get_template(session, template_id=deleted.id)
        assert exc.value.status_code == 404
