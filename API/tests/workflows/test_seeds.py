"""Pin tests for Step-20 seeded workflows.

Covers:

  * ``install_seeded_workflows`` creates 15 draft rows in a fresh org.
  * Re-running ``install_seeded_workflows`` is idempotent (no dupes).
  * Each seeded workflow lands as ``status='draft'`` (operator review
    before activation).
  * Each seeded workflow carries the documented ``re_enrollment_rule``.
  * Seed names align with ``templates_gallery.CATALOG`` ids so the
    operator can match canvas rows back to the gallery entry.
  * ``create_organization`` runs the seeder transitively (the
    Step-20 provisioning hook).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.tenants.service import create_organization
from src.app.core.workflows import templates_gallery as wf_gallery
from src.app.core.workflows.models import Workflow, WorkflowStatus
from src.app.core.workflows.seeds import install_seeded_workflows
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_id(test_db):
    """Fresh org WITHOUT going through ``create_organization`` so the
    seeder tests run against an empty workflows table for the org."""
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "SeedsDemo",
            "slug": f"sdem-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _list_workflows(test_db, org_id):
    return list(
        (
            await test_db.execute(
                select(Workflow).where(Workflow.org_id == org_id)
            )
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Install + idempotency
# ---------------------------------------------------------------------------


async def test_install_seeded_workflows_creates_full_catalogue(test_db, org_id):
    """A fresh org gets exactly len(CATALOG) draft workflows."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        rows = await _list_workflows(test_db, org_id)
    finally:
        reset_context(token)

    assert result["installed"] == len(wf_gallery.CATALOG)
    assert result["skipped"] == 0
    assert len(rows) == len(wf_gallery.CATALOG)
    for wf in rows:
        assert wf.status == WorkflowStatus.draft


async def test_install_seeded_workflows_is_idempotent(test_db, org_id):
    """Re-running the seeder on the same org doesn't create duplicates."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        second = await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        rows = await _list_workflows(test_db, org_id)
    finally:
        reset_context(token)

    assert second["installed"] == 0
    assert second["skipped"] == len(wf_gallery.CATALOG)
    assert len(rows) == len(wf_gallery.CATALOG)


# ---------------------------------------------------------------------------
# Per-seed metadata
# ---------------------------------------------------------------------------


async def test_seed_re_enrollment_rules_match_catalogue(test_db, org_id):
    """Each seeded row's ``re_enrollment_rule`` matches the gallery
    entry's declaration — operator's gallery promise is preserved
    on clone."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        rows = await _list_workflows(test_db, org_id)
    finally:
        reset_context(token)

    by_name = {wf.name: wf for wf in rows}
    for entry in wf_gallery.CATALOG:
        assert entry.name in by_name, f"missing seed: {entry.name}"
        wf = by_name[entry.name]
        assert wf.re_enrollment_rule.value == entry.re_enrollment_rule, (
            f"{entry.name}: expected {entry.re_enrollment_rule}, "
            f"got {wf.re_enrollment_rule.value}"
        )


async def test_seed_names_match_catalogue(test_db, org_id):
    """Seed names round-trip from catalogue → DB so the gallery UI
    can match a draft row back to the gallery card it came from."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        rows = await _list_workflows(test_db, org_id)
    finally:
        reset_context(token)

    seeded_names = {wf.name for wf in rows}
    catalog_names = {entry.name for entry in wf_gallery.CATALOG}
    assert seeded_names == catalog_names


async def test_seed_has_at_least_one_marketing_workflow(test_db, org_id):
    """``is_marketing=True`` rows are subject to the Step-12 compliance
    gate at activation. At least one seed has it set — verifies the
    gallery's ``is_marketing`` propagation."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        rows = await _list_workflows(test_db, org_id)
    finally:
        reset_context(token)

    assert any(wf.is_marketing for wf in rows)


# ---------------------------------------------------------------------------
# Provisioning hook
# ---------------------------------------------------------------------------


async def test_create_organization_runs_seeder(test_db):
    """A brand new org goes through the full provisioning path, which
    includes the Step-20 seed install. Verifies the hook in
    ``create_organization`` calls into ``install_seeded_workflows``."""
    org = await create_organization(test_db, name="HookDemo")
    await test_db.commit()
    rows = await _list_workflows(test_db, org.id)
    assert len(rows) == len(wf_gallery.CATALOG)
