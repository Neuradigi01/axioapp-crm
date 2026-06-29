"""Pin tests for the Step-5 "User Welcome" template seeder.

The seeder runs inside the org-create transaction so a fresh org
always lands with a published Welcome template ready for the
automation engine to render. The companion trigger seeder lives
under `core/automation/seeds.py` (covered in `test_user_signed_up.py`).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateVersion,
    TemplateExternalStatus,
    TemplateInternalStatus,
)
from src.app.core.templates.seeds import seed_user_welcome_template
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def test_seeds_a_published_email_template(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        template = await seed_user_welcome_template(test_db, org_id=org_id)
        await test_db.commit()
    finally:
        reset_context(token)

    assert template.org_id == org_id
    assert template.name == "User Welcome"
    assert template.channel == ConversationChannel.email
    assert template.internal_status == TemplateInternalStatus.published
    assert template.external_status == TemplateExternalStatus.n_a
    assert "{{ user.full_name }}" in template.body_text
    assert "{{ org.name }}" in template.body_text
    assert template.subject == "Welcome to {{ org.name }}"
    assert "user.full_name" in template.variables
    assert "org.name" in template.variables


async def test_seeds_version_row(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        template = await seed_user_welcome_template(test_db, org_id=org_id)
        await test_db.commit()
    finally:
        reset_context(token)

    rows = (
        await test_db.execute(
            select(MessageTemplateVersion).where(
                MessageTemplateVersion.template_id == template.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].version == 1
    assert rows[0].body_text == template.body_text


async def test_seed_is_idempotent(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        first = await seed_user_welcome_template(test_db, org_id=org_id)
        await test_db.commit()
        second = await seed_user_welcome_template(test_db, org_id=org_id)
        await test_db.commit()
    finally:
        reset_context(token)

    assert first.id == second.id

    count = (
        await test_db.execute(
            select(MessageTemplate).where(
                MessageTemplate.org_id == org_id,
                MessageTemplate.name == "User Welcome",
            )
        )
    ).scalars().all()
    assert len(count) == 1
