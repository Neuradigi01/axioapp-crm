"""Installer idempotency + per-section seed coverage.

Builds a small in-memory manifest, runs the installer twice against
the same org, then asserts:
  - row counts after the first run match the manifest
  - row counts after the second run are unchanged
  - the org's `template_id` + `template_version` columns are stamped
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.app.core.calls.models import CallOutcome
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldSource,
)
from src.app.core.packs.installer import install
from src.app.core.packs.loader import load_pack_dict
from src.app.core.packs.models import LeadSource
from src.app.core.permissions.models import Permission, Role, RolePermission
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.core.settings.models import OrgSettings
from src.app.core.tenants.models import Organization


def _tiny_manifest() -> dict:
    return {
        "template_id": "tinypack",
        "version": "0.2.0",
        "display_name": "Tiny",
        "pipelines": [
            {
                "key": "leads",
                "name": "Leads",
                "stages": [
                    {"key": "new", "name": "New", "display_order": 0},
                    {"key": "won", "name": "Won", "display_order": 1, "is_won": True},
                    {"key": "lost", "name": "Lost", "display_order": 2, "is_lost": True},
                ],
            }
        ],
        "custom_fields": [
            {
                "entity_type": "lead",
                "field_key": "budget",
                "field_label": "Budget",
                "field_type": "currency",
                "display_order": 0,
            }
        ],
        "roles": [
            {
                "key": "store_manager",
                "name": "Store Manager",
                "permissions": ["contacts.read", "leads.*"],
            }
        ],
        "module_permissions": {
            "leads": ["leads.read", "leads.write"],
        },
        "lead_sources": [
            {"key": "walk-in", "label": "Walk-in", "display_order": 10},
            {"key": "website", "label": "Website", "display_order": 20},
        ],
        "call_outcomes": [
            {"key": "store_visit_booked", "label": "Store visit booked",
             "color": "#10b981", "display_order": 60},
        ],
        "defaults": {
            "currency": "INR",
            "tax_rate": 18,
            "timezone": "Asia/Kolkata",
            "ai_personality": "Friendly + concise",
            "ai_welcome_message": "Hi, how can we help?",
        },
    }


@pytest.mark.asyncio
async def test_install_creates_then_idempotent(test_db, seeded_admin):
    org = seeded_admin["org"]
    manifest = load_pack_dict(_tiny_manifest())

    # Run #1 — fresh install.
    report1 = await install(test_db, org_id=org.id, manifest=manifest)
    assert report1.errors == []
    assert report1.pipelines_created == 1
    assert report1.stages_created == 3
    assert report1.custom_fields_created == 1
    assert report1.roles_created == 1
    # leads.* expands to leads.read + leads.write = 2 perms
    assert report1.role_permissions_added == 3  # contacts.read + 2 leads.*
    assert report1.lead_sources_created == 2
    assert report1.call_outcomes_created == 1
    # Defaults: store_name/etc start at their migration defaults so
    # `currency=INR` matches → no change applied. AI fields ARE applied
    # (start null).
    assert "ai_personality" in report1.defaults_applied
    assert "ai_welcome_message" in report1.defaults_applied

    # Org stamped.
    await test_db.refresh(org)
    assert org.template_id == "tinypack"
    assert org.template_version == "0.2.0"

    # Row counts in DB.
    n_pipelines = (
        await test_db.execute(
            select(func.count()).select_from(Pipeline).where(Pipeline.org_id == org.id)
        )
    ).scalar_one()
    n_stages = (
        await test_db.execute(
            select(func.count()).select_from(PipelineStage).where(PipelineStage.org_id == org.id)
        )
    ).scalar_one()
    n_cf = (
        await test_db.execute(
            select(func.count()).select_from(CustomFieldDefinition).where(CustomFieldDefinition.org_id == org.id)
        )
    ).scalar_one()
    n_sources = (
        await test_db.execute(
            select(func.count()).select_from(LeadSource).where(LeadSource.org_id == org.id)
        )
    ).scalar_one()
    n_outcomes = (
        await test_db.execute(
            select(func.count()).select_from(CallOutcome).where(CallOutcome.org_id == org.id)
        )
    ).scalar_one()
    assert (n_pipelines, n_stages, n_cf, n_sources, n_outcomes) == (1, 3, 1, 2, 1)

    # Run #2 — must be a no-op.
    report2 = await install(test_db, org_id=org.id, manifest=manifest)
    assert report2.errors == []
    assert report2.pipelines_created == 0
    assert report2.stages_created == 0
    assert report2.custom_fields_created == 0
    assert report2.roles_created == 0
    assert report2.lead_sources_created == 0
    assert report2.call_outcomes_created == 0
    # Defaults already applied → nothing in `defaults_applied` second run.
    assert report2.defaults_applied == []

    # Row counts unchanged.
    n_pipelines2 = (
        await test_db.execute(
            select(func.count()).select_from(Pipeline).where(Pipeline.org_id == org.id)
        )
    ).scalar_one()
    assert n_pipelines2 == n_pipelines

    # Pack-sourced custom field landed with source='pack' + pack_id set.
    cf = (
        await test_db.execute(
            select(CustomFieldDefinition).where(
                CustomFieldDefinition.org_id == org.id,
                CustomFieldDefinition.field_key == "budget",
            )
        )
    ).scalar_one()
    assert cf.source == FieldSource.pack
    assert cf.pack_id == "tinypack"

    # Role got 3 permissions (contacts.read + leads.read + leads.write).
    role = (
        await test_db.execute(
            select(Role).where(Role.org_id == org.id, Role.name == "Store Manager")
        )
    ).scalar_one()
    granted = (
        await test_db.execute(
            select(Permission.key)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        )
    ).scalars().all()
    assert set(granted) == {"contacts.read", "leads.read", "leads.write"}


@pytest.mark.asyncio
async def test_install_unknown_org_returns_error_report(
    test_db, seeded_admin
):
    import uuid

    manifest = load_pack_dict(_tiny_manifest())
    report = await install(test_db, org_id=uuid.uuid4(), manifest=manifest)
    assert report.errors
    assert "not found" in report.errors[0].lower()
    assert report.pipelines_created == 0
