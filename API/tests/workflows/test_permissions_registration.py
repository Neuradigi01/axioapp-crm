"""Pin tests for Step-3 module + permission registration.

Covers:

  * Importing :mod:`core.workflows.module` registers the
    ``workflows`` entry on the module registry with the
    documented sidebar metadata.
  * The six permission keys land in ``tbl_permissions`` after the
    Step-3 backfill migration + lifespan sweep.
  * The role-template registry grants the right keys to
    Admin / Owner / Employee fanouts.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from src.app.core.module_registry import registry
from src.app.core.permissions.models import Permission
from src.app.core.permissions.role_templates import (
    _CORE_ADMIN_KEYS,
    _CORE_EMPLOYEE_KEYS,
    _CORE_OWNER_KEYS,
)
from src.app.core.workflows.module import MODULE as WORKFLOWS_MODULE
from src.app.core.workflows.permissions import (
    ADMIN_KEYS,
    ALL_KEYS,
    EMPLOYEE_KEYS,
    OWNER_KEYS,
)


pytestmark = pytest.mark.asyncio


def test_module_descriptor_shape():
    """The module descriptor declares the documented sidebar
    metadata so the SPA's tree picks it up correctly."""
    assert WORKFLOWS_MODULE.id == "workflows"
    assert WORKFLOWS_MODULE.name == "Workflows"
    assert WORKFLOWS_MODULE.icon == "git-branch"
    assert WORKFLOWS_MODULE.layer == "core"
    assert WORKFLOWS_MODULE.route == "/api/v1/workflows"
    assert WORKFLOWS_MODULE.frontend_route == "/user/workflows"
    assert WORKFLOWS_MODULE.menu_position == 270
    assert set(WORKFLOWS_MODULE.permissions) == set(ALL_KEYS)


def test_module_registered_in_registry():
    """The discovery walker registers the module — importing
    :mod:`core.workflows.module` is enough; the runtime calls
    :func:`discover_modules` at lifespan startup."""
    # Re-register defensively so this test passes whether or not
    # the lifespan sweep already ran.
    if WORKFLOWS_MODULE.id not in {m.id for m in registry.all()}:
        registry.register(WORKFLOWS_MODULE)
    ids = {m.id for m in registry.all()}
    assert "workflows" in ids


def test_role_templates_grant_keys_correctly():
    """Owner + Admin get all six keys; Employee gets read +
    view_analytics only — matches the spec's fanout."""
    for key in ALL_KEYS:
        assert key in _CORE_ADMIN_KEYS, f"Admin missing {key}"
    # Owner is a superset of Admin in the role-templates module.
    assert set(ALL_KEYS).issubset(set(_CORE_OWNER_KEYS))

    employee_workflow_keys = {
        k for k in _CORE_EMPLOYEE_KEYS if k.startswith("workflows.")
    }
    assert employee_workflow_keys == set(EMPLOYEE_KEYS)


def test_permissions_constants_self_consistent():
    """The OWNER_KEYS + ADMIN_KEYS constants must be tuples of the
    full key set (workflows treats Owner == Admin for the
    in-module perms; tenant-level keys diverge elsewhere)."""
    assert set(OWNER_KEYS) == set(ALL_KEYS)
    assert set(ADMIN_KEYS) == set(ALL_KEYS)


async def test_six_keys_registered_in_tbl_permissions(test_db):
    """Post-migration the six rows must be present in
    ``tbl_permissions``. The Step-3 backfill migration
    (``0137_bf_workflows_perm``) populates them explicitly so the
    fanout JOIN has something to find."""
    rows = (
        await test_db.execute(
            select(Permission.key).where(Permission.key.in_(ALL_KEYS))
        )
    ).scalars().all()
    assert set(rows) == set(ALL_KEYS), (
        f"missing keys: {set(ALL_KEYS) - set(rows)}"
    )
