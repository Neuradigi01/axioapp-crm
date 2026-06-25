"""Service-layer tests for ``core.templates.service``.

Exercises:

* :func:`create_template` writes the parent + v=1 row in one txn and
  populates the parsed ``variables`` list.
* The functional unique index raises a :class:`DuplicateTemplateName`
  on a same-channel rename, but the same name on a different channel
  is fine.
* :func:`update_template` bumps ``current_version``, writes a new
  version row, and is locked once status leaves ``draft``.
* :func:`list_templates` filters by channel / status / search and
  paginates.
* RLS isolates rows across orgs.
* :func:`archive_template` is idempotent.

Uses the function-scoped ``test_db`` fixture from ``conftest.py``
which creates + drops every table per test.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import service as templates_service
from src.app.core.templates.exceptions import (
    DuplicateTemplateName,
    TemplateLocked,
    TemplateNotFound,
)
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateVersion,
    TemplateCategory,
    TemplateInternalStatus,
)
from src.app.core.templates.schemas import TemplateCreate, TemplateUpdate
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def two_orgs(test_db):
    """Seed two organization rows for cross-tenant tests.

    Inserts via raw SQL because the layered ``Organization`` mapper
    requires more fields than this test needs and the conftest's
    ``seeded_admin`` fixture is overkill for the templates path. We
    just need two valid ``tbl_organizations.id`` FK targets so the
    template inserts don't violate.
    """
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    for org_id, slug in ((org_a, "org-a"), (org_b, "org-b")):
        await test_db.execute(
            sql_text(
                "INSERT INTO tbl_organizations (id, name, slug) "
                "VALUES (:id, :name, :slug)"
            ),
            {"id": str(org_id), "name": slug, "slug": slug},
        )
    await test_db.commit()
    return {"a": org_a, "b": org_b}


def _payload(
    *,
    name: str = "Welcome",
    channel: ConversationChannel = ConversationChannel.email,
    body: str = "Hi {{ contact.first_name }}",
    subject: str | None = "Welcome to {{ org.name }}",
    preview: str | None = None,
) -> TemplateCreate:
    """Minimal valid create payload — defaults to a well-formed email
    template since email is the most-asserted-against channel below."""
    if channel != ConversationChannel.email:
        subject = None
        preview = None
    return TemplateCreate(
        name=name,
        channel=channel,
        category=TemplateCategory.marketing,
        body_text=body,
        subject=subject,
        preview_text=preview,
    )


# --- create -------------------------------------------------------------


async def test_create_template_writes_version_1(test_db, two_orgs):
    token = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        template = await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(),
        )
        assert template.current_version == 1
        assert template.internal_status == TemplateInternalStatus.draft
        # Variables parsed from the body, not whatever the client supplied.
        assert "contact.first_name" in template.variables
        assert "org.name" in template.variables

        # The v=1 row exists.
        version = (
            await test_db.execute(
                select(MessageTemplateVersion).where(
                    MessageTemplateVersion.template_id == template.id,
                    MessageTemplateVersion.version == 1,
                )
            )
        ).scalar_one()
        assert version.change_note == "Initial version"
    finally:
        reset_context(token)


async def test_create_rejects_duplicate_name_same_channel(test_db, two_orgs):
    token = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(name="Welcome"),
        )
        with pytest.raises(DuplicateTemplateName):
            await templates_service.create_template(
                test_db,
                org_id=two_orgs["a"],
                user_id=None,
                payload=_payload(name="welcome"),  # lower() collision
            )
    finally:
        reset_context(token)


async def test_create_allows_same_name_across_channels(test_db, two_orgs):
    token = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(
                name="Welcome", channel=ConversationChannel.email
            ),
        )
        # Same name on WhatsApp is a different (org_id, name, channel) key.
        t2 = await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(
                name="Welcome", channel=ConversationChannel.whatsapp
            ),
        )
        assert t2.channel == ConversationChannel.whatsapp
    finally:
        reset_context(token)


async def test_create_allows_same_name_across_orgs(test_db, two_orgs):
    """Different tenants are independent — Org A and Org B can both
    have a 'Welcome' template."""
    token_a = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(name="Welcome"),
        )
    finally:
        reset_context(token_a)

    token_b = set_context(RequestContext(org_id=two_orgs["b"]))
    try:
        t = await templates_service.create_template(
            test_db,
            org_id=two_orgs["b"],
            user_id=None,
            payload=_payload(name="Welcome"),
        )
        assert t.org_id == two_orgs["b"]
    finally:
        reset_context(token_b)


# --- update -------------------------------------------------------------


async def test_update_bumps_version_and_writes_history(test_db, two_orgs):
    token = set_context(
        RequestContext(org_id=two_orgs["a"], user_id=uuid.uuid4())
    )
    try:
        template = await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(body="Old body {{ contact.first_name }}"),
        )

        updated = await templates_service.update_template(
            test_db,
            org_id=two_orgs["a"],
            template_id=template.id,
            user_id=None,
            payload=TemplateUpdate(
                body_text="New body {{ contact.first_name }} {{ org.name }}",
                change_note="rewrote intro",
            ),
        )
        assert updated.current_version == 2
        assert "org.name" in updated.variables

        # Both versions exist.
        rows = (
            await test_db.execute(
                select(MessageTemplateVersion)
                .where(MessageTemplateVersion.template_id == template.id)
                .order_by(MessageTemplateVersion.version.asc())
            )
        ).scalars().all()
        assert [r.version for r in rows] == [1, 2]
        assert rows[1].change_note == "rewrote intro"
    finally:
        reset_context(token)


async def test_update_locked_on_non_draft(test_db, two_orgs):
    token = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        template = await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(),
        )
        # Simulate Step-4 workflow nudging the template into in_review.
        template.internal_status = TemplateInternalStatus.in_review
        await test_db.commit()

        with pytest.raises(TemplateLocked) as info:
            await templates_service.update_template(
                test_db,
                org_id=two_orgs["a"],
                template_id=template.id,
                user_id=None,
                payload=TemplateUpdate(body_text="changed"),
            )
        assert info.value.status == "in_review"
    finally:
        reset_context(token)


async def test_update_no_change_is_noop(test_db, two_orgs):
    """``update_template`` with an empty payload (or identical values)
    leaves ``current_version`` alone — no spurious version-2 row."""
    token = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        template = await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(),
        )
        same = await templates_service.update_template(
            test_db,
            org_id=two_orgs["a"],
            template_id=template.id,
            user_id=None,
            payload=TemplateUpdate(),
        )
        assert same.current_version == 1
    finally:
        reset_context(token)


# --- list ---------------------------------------------------------------


async def test_list_filters_and_paginates(test_db, two_orgs):
    token = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        for i in range(4):
            await templates_service.create_template(
                test_db,
                org_id=two_orgs["a"],
                user_id=None,
                payload=_payload(name=f"Email {i}"),
            )
        await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(name="WA one", channel=ConversationChannel.whatsapp),
        )

        rows, total = await templates_service.list_templates(
            test_db,
            org_id=two_orgs["a"],
            channel=ConversationChannel.email,
        )
        assert total == 4
        assert all(r.channel == ConversationChannel.email for r in rows)

        page, page_total = await templates_service.list_templates(
            test_db,
            org_id=two_orgs["a"],
            channel=ConversationChannel.email,
            limit=2,
            offset=0,
        )
        assert page_total == 4
        assert len(page) == 2

        # Search by name substring (case-insensitive).
        hits, hits_total = await templates_service.list_templates(
            test_db,
            org_id=two_orgs["a"],
            q="email 1",
        )
        assert hits_total == 1
        assert hits[0].name == "Email 1"
    finally:
        reset_context(token)


# --- archive ------------------------------------------------------------


async def test_archive_is_idempotent(test_db, two_orgs):
    token = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        template = await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(),
        )
        archived = await templates_service.archive_template(
            test_db,
            org_id=two_orgs["a"],
            template_id=template.id,
            user_id=None,
        )
        assert archived.internal_status == TemplateInternalStatus.archived

        # Second call returns the same row without raising.
        again = await templates_service.archive_template(
            test_db,
            org_id=two_orgs["a"],
            template_id=template.id,
            user_id=None,
        )
        assert again.internal_status == TemplateInternalStatus.archived
    finally:
        reset_context(token)


# --- not found / RLS ----------------------------------------------------


async def test_get_template_not_found_returns_typed_exception(test_db, two_orgs):
    token = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        with pytest.raises(TemplateNotFound):
            await templates_service.get_template(
                test_db,
                org_id=two_orgs["a"],
                template_id=uuid.uuid4(),
            )
    finally:
        reset_context(token)


async def test_cross_org_read_is_blocked(test_db, two_orgs):
    """Org A creates a template; Org B asks for it by id → 404 (RLS +
    explicit org_id filter)."""
    token_a = set_context(RequestContext(org_id=two_orgs["a"]))
    try:
        template = await templates_service.create_template(
            test_db,
            org_id=two_orgs["a"],
            user_id=None,
            payload=_payload(),
        )
        template_id = template.id
    finally:
        reset_context(token_a)

    token_b = set_context(RequestContext(org_id=two_orgs["b"]))
    try:
        with pytest.raises(TemplateNotFound):
            await templates_service.get_template(
                test_db,
                org_id=two_orgs["b"],
                template_id=template_id,
            )
    finally:
        reset_context(token_b)
