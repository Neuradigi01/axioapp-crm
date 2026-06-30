"""Furniture pack — install on a fresh org and assert section counts.

Uses the actual `src/app/packs/furniture/pack.yaml` shipped with the
build (not a fixture). The fresh `test_db` schema means no prior
pipelines exist, so the leads pipeline gets seeded fully (5 stages
matching the screenshot + 1 lost = 6 stages total).

Expected counts per the step file:
  - 6 lead stages  (New + Contacted + Showroom Visit + Quotation + Won + Lost)
  - 7 custom-order stages
  - 7 roles
  - 7 lead sources
  - 6 call outcomes
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.app.core.calls.models import CallOutcome
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldSource,
)
from src.app.core.packs.installer import install
from src.app.core.packs.loader import load_pack
from src.app.core.packs.models import LeadSource
from src.app.core.permissions.models import Role
from src.app.core.pipelines.models import Pipeline, PipelineStage


def _pack_path() -> Path:
    """Resolve `src/app/packs/furniture/pack.yaml` from CWD or the
    container's `/app` mount."""
    candidates = [
        Path("src/app/packs/furniture/pack.yaml"),
        Path("/app/src/app/packs/furniture/pack.yaml"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"furniture pack.yaml not found in any of: {candidates}")


@pytest.mark.asyncio
async def test_furniture_pack_seeds_expected_counts(test_db, seeded_admin):
    org = seeded_admin["org"]
    manifest = load_pack(_pack_path())

    report = await install(test_db, org_id=org.id, manifest=manifest)
    assert report.errors == [], report.errors

    # Stamp
    await test_db.refresh(org)
    assert org.template_id == "furniture"
    assert org.template_version == "1.0.0"

    # Pipelines: 2 total
    n_pipelines = (
        await test_db.execute(
            select(func.count()).select_from(Pipeline).where(Pipeline.org_id == org.id)
        )
    ).scalar_one()
    assert n_pipelines == 2

    # Leads pipeline — 6 stages (5 progression + 1 lost)
    leads = (
        await test_db.execute(
            select(Pipeline).where(Pipeline.org_id == org.id, Pipeline.key == "leads")
        )
    ).scalar_one()
    leads_stages = (
        (
            await test_db.execute(
                select(PipelineStage)
                .where(PipelineStage.pipeline_id == leads.id)
                .order_by(PipelineStage.display_order)
            )
        )
        .scalars()
        .all()
    )
    leads_keys = [s.key for s in leads_stages]
    assert leads_keys == [
        "new",
        "contacted",
        "showroom_visit",
        "quotation",
        "won",
        "lost",
    ]
    assert any(s.is_won for s in leads_stages)
    assert any(s.is_lost for s in leads_stages)

    # Custom orders pipeline — 7 stages
    co = (
        await test_db.execute(
            select(Pipeline).where(Pipeline.org_id == org.id, Pipeline.key == "custom_orders")
        )
    ).scalar_one()
    co_stages = (
        (
            await test_db.execute(
                select(PipelineStage)
                .where(PipelineStage.pipeline_id == co.id)
                .order_by(PipelineStage.display_order)
            )
        )
        .scalars()
        .all()
    )
    assert len(co_stages) == 7
    assert [s.key for s in co_stages][0] == "measurement_scheduled"
    assert [s.key for s in co_stages][-1] == "cancelled"

    # Roles: 7
    n_roles = (
        await test_db.execute(select(func.count()).select_from(Role).where(Role.org_id == org.id))
    ).scalar_one()
    assert n_roles == 7

    # Lead sources: 7
    n_sources = (
        await test_db.execute(
            select(func.count()).select_from(LeadSource).where(LeadSource.org_id == org.id)
        )
    ).scalar_one()
    assert n_sources == 7

    # Call outcomes: 6
    n_outcomes = (
        await test_db.execute(
            select(func.count()).select_from(CallOutcome).where(CallOutcome.org_id == org.id)
        )
    ).scalar_one()
    assert n_outcomes == 6

    # Custom fields: at least 11 pack-sourced (matches the manifest)
    n_cf = (
        await test_db.execute(
            select(func.count())
            .select_from(CustomFieldDefinition)
            .where(CustomFieldDefinition.org_id == org.id)
            .where(CustomFieldDefinition.source == FieldSource.pack)
        )
    ).scalar_one()
    assert n_cf == 11


@pytest.mark.asyncio
async def test_furniture_pack_install_is_idempotent(test_db, seeded_admin):
    org = seeded_admin["org"]
    manifest = load_pack(_pack_path())

    await install(test_db, org_id=org.id, manifest=manifest)
    report2 = await install(test_db, org_id=org.id, manifest=manifest)

    assert report2.errors == []
    assert report2.pipelines_created == 0
    assert report2.stages_created == 0
    assert report2.custom_fields_created == 0
    assert report2.roles_created == 0
    assert report2.lead_sources_created == 0
    assert report2.call_outcomes_created == 0
