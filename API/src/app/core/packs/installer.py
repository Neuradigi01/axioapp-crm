"""Pack installer — idempotent seed of every pack-driven table.

Reads a `PackManifest` and upserts:
  1. `pipelines` + `pipeline_stages`     (by `(org_id, pipeline_key)` + stage key)
  2. `custom_field_definitions`           (by `(org_id, entity_type, field_key)`)
  3. `roles` + `role_permissions`         (by `(org_id, role_name)`)
  4. `lead_sources`                       (by `(org_id, key)`)
  5. `call_outcomes`                      (by `(org_id, key)`)
  6. `org_settings` defaults              (only for fields the admin
                                             hasn't customized yet)
  7. `organizations.template_id` + `template_version`

Every section runs in its own try/except. A section that throws is
logged + audited but does NOT abort the whole install — partial seed
is better than no seed. The caller (CLI / tests) gets back an
`InstallReport` summary with per-section counts so failures are loud.

Idempotency is preserved everywhere by `ON CONFLICT DO NOTHING` or
explicit existence checks before INSERT.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.calls.models import CallOutcome
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldSource,
    FieldType,
)
from src.app.core.packs.manifest import PackManifest
from src.app.core.packs.models import LeadSource
from src.app.core.permissions.models import Role, RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.core.settings.service import get_or_create as get_or_create_settings
from src.app.core.tenants import data_access

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InstallReport:
    template_id: str
    version: str
    pipelines_created: int = 0
    pipelines_skipped: int = 0
    stages_created: int = 0
    custom_fields_created: int = 0
    custom_fields_skipped: int = 0
    roles_created: int = 0
    roles_skipped: int = 0
    role_permissions_added: int = 0
    lead_sources_created: int = 0
    lead_sources_skipped: int = 0
    call_outcomes_created: int = 0
    call_outcomes_skipped: int = 0
    defaults_applied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "version": self.version,
            "pipelines_created": self.pipelines_created,
            "pipelines_skipped": self.pipelines_skipped,
            "stages_created": self.stages_created,
            "custom_fields_created": self.custom_fields_created,
            "custom_fields_skipped": self.custom_fields_skipped,
            "roles_created": self.roles_created,
            "roles_skipped": self.roles_skipped,
            "role_permissions_added": self.role_permissions_added,
            "lead_sources_created": self.lead_sources_created,
            "lead_sources_skipped": self.lead_sources_skipped,
            "call_outcomes_created": self.call_outcomes_created,
            "call_outcomes_skipped": self.call_outcomes_skipped,
            "defaults_applied": list(self.defaults_applied),
            "errors": list(self.errors),
        }


async def install(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    manifest: PackManifest,
) -> InstallReport:
    """Run the installer end-to-end for one org. Idempotent.

    Each section's failure is captured in `report.errors` but the
    other sections continue. The function never raises into the
    caller; it returns a report the caller can act on.
    """
    report = InstallReport(template_id=manifest.template_id, version=manifest.version)

    org = await data_access.get_organization_by_id(session, org_id)
    if org is None:
        report.errors.append(f"organization {org_id} not found")
        return report

    await _section(
        "pipelines",
        _install_pipelines(session, org_id=org_id, manifest=manifest, report=report),
        report,
    )
    await _section(
        "custom_fields",
        _install_custom_fields(session, org_id=org_id, manifest=manifest, report=report),
        report,
    )
    await _section(
        "roles",
        _install_roles(session, org_id=org_id, manifest=manifest, report=report),
        report,
    )
    await _section(
        "lead_sources",
        _install_lead_sources(session, org_id=org_id, manifest=manifest, report=report),
        report,
    )
    await _section(
        "call_outcomes",
        _install_call_outcomes(session, org_id=org_id, manifest=manifest, report=report),
        report,
    )
    await _section(
        "defaults",
        _install_defaults(session, org_id=org_id, manifest=manifest, report=report),
        report,
    )

    # Stamp the org with template_id + template_version.
    org.template_id = manifest.template_id
    org.template_version = manifest.version
    await session.commit()

    await audit.log(
        "packs.installed",
        entity_type="organization",
        entity_id=org_id,
        org_id=org_id,
        after=report.as_dict(),
    )
    return report


async def _section(name: str, coro, report: InstallReport) -> None:
    """Wrap a section coroutine so failures don't abort the install."""
    try:
        await coro
    except Exception as exc:  # noqa: BLE001 - section isolation by design
        logger.exception("pack installer section %s failed", name)
        report.errors.append(f"{name}: {exc}")


# --- 1. pipelines ---------------------------------------------------------


async def _install_pipelines(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    manifest: PackManifest,
    report: InstallReport,
) -> None:
    """Pipelines are installed as a unit. If the pipeline already
    exists we leave its stages alone — the admin may have renamed
    or reordered them. Re-installing the pack should never overwrite
    operator changes. Only freshly-created pipelines get their full
    stage set seeded."""
    for p in manifest.pipelines:
        existing = (
            await session.execute(
                select(Pipeline).where(Pipeline.org_id == org_id).where(Pipeline.key == p.key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            report.pipelines_skipped += 1
            continue

        pipeline = Pipeline(org_id=org_id, key=p.key, name=p.name)
        session.add(pipeline)
        await session.flush()
        report.pipelines_created += 1

        for stage in p.stages:
            session.add(
                PipelineStage(
                    org_id=org_id,
                    pipeline_id=pipeline.id,
                    key=stage.key,
                    name=stage.name,
                    color=stage.color,
                    display_order=stage.display_order,
                    is_won=stage.is_won,
                    is_lost=stage.is_lost,
                )
            )
            report.stages_created += 1
    await session.commit()


# --- 2. custom fields -----------------------------------------------------


async def _install_custom_fields(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    manifest: PackManifest,
    report: InstallReport,
) -> None:
    for cf in manifest.custom_fields:
        try:
            field_type = FieldType(cf.field_type)
        except ValueError:
            report.errors.append(
                f"custom_fields: unknown field_type {cf.field_type!r} for "
                f"{cf.entity_type}.{cf.field_key}"
            )
            continue

        existing = (
            await session.execute(
                select(CustomFieldDefinition)
                .where(CustomFieldDefinition.org_id == org_id)
                .where(CustomFieldDefinition.entity_type == cf.entity_type)
                .where(CustomFieldDefinition.field_key == cf.field_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            report.custom_fields_skipped += 1
            continue

        # Pack manifests carry `options` as a flat YAML list for
        # readability; the CustomFieldDefinition JSONB column stores it
        # as `{"choices": [...]}` (contract shared with user-created
        # fields and the render schema). Wrap here so downstream reads
        # don't have to branch on shape.
        options_value: dict[str, Any] | None = (
            {"choices": list(cf.options)} if cf.options is not None else None
        )

        session.add(
            CustomFieldDefinition(
                org_id=org_id,
                entity_type=cf.entity_type,
                field_key=cf.field_key,
                field_label=cf.field_label,
                field_type=field_type,
                options=options_value,
                is_required=cf.is_required,
                is_hidden=cf.is_hidden,
                display_order=cf.display_order,
                source=FieldSource.pack,
                # CustomFieldDefinition.pack_id stays as-is in this
                # rename scope — it's a separate column on a different
                # table (`custom_field_definitions`) recording which
                # template originated the field, distinct from the
                # tenant's chosen template on `organizations`.
                pack_id=manifest.template_id,
                validation=cf.validation,
            )
        )
        report.custom_fields_created += 1
    await session.commit()


# --- 3. roles + role_permissions ------------------------------------------


async def _install_roles(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    manifest: PackManifest,
    report: InstallReport,
) -> None:
    for r in manifest.roles:
        existing = (
            await session.execute(
                select(Role).where(Role.org_id == org_id).where(Role.name == r.name)
            )
        ).scalar_one_or_none()
        if existing is None:
            role = Role(org_id=org_id, name=r.name, is_system=True)
            session.add(role)
            await session.flush()
            report.roles_created += 1
        else:
            role = existing
            report.roles_skipped += 1

        # Resolve `<module>.*` shorthands via `module_permissions`.
        expanded: list[str] = []
        for key in r.permissions:
            if key.endswith(".*"):
                module_id = key[:-2]
                expanded.extend(manifest.module_permissions.get(module_id, []))
            else:
                expanded.append(key)

        for perm_key in dict.fromkeys(expanded):  # dedupe, preserve order
            perm = await register_permission(
                session,
                key=perm_key,
                module=perm_key.split(".", 1)[0],
                description=perm_key,
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role.id, permission_id=perm.id)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
            report.role_permissions_added += 1
    await session.commit()


# --- 4. lead sources -----------------------------------------------------


async def _install_lead_sources(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    manifest: PackManifest,
    report: InstallReport,
) -> None:
    for ls in manifest.lead_sources:
        existing = (
            await session.execute(
                select(LeadSource)
                .where(LeadSource.org_id == org_id)
                .where(LeadSource.key == ls.key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            report.lead_sources_skipped += 1
            continue
        session.add(
            LeadSource(
                org_id=org_id,
                key=ls.key,
                label=ls.label,
                display_order=ls.display_order,
            )
        )
        report.lead_sources_created += 1
    await session.commit()


# --- 5. call outcomes ----------------------------------------------------


async def _install_call_outcomes(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    manifest: PackManifest,
    report: InstallReport,
) -> None:
    for co in manifest.call_outcomes:
        try:
            session.add(
                CallOutcome(
                    org_id=org_id,
                    key=co.key,
                    label=co.label,
                    color=co.color,
                    display_order=co.display_order,
                )
            )
            await session.flush()
            report.call_outcomes_created += 1
        except IntegrityError:
            await session.rollback()
            report.call_outcomes_skipped += 1
    await session.commit()


# --- 6. defaults (only fields not already customized) --------------------


async def _install_defaults(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    manifest: PackManifest,
    report: InstallReport,
) -> None:
    settings = await get_or_create_settings(session, org_id=org_id)
    d = manifest.defaults

    changed: list[str] = []
    # For numeric/string columns with non-null server_default we treat
    # "still at default" as "matches the migration default value".
    if d.currency is not None and settings.currency == "INR":
        settings.currency = d.currency
        changed.append("currency")
    if d.tax_rate is not None and str(settings.tax_rate) == "18.00":
        settings.tax_rate = d.tax_rate
        changed.append("tax_rate")
    if d.timezone is not None and settings.timezone == "Asia/Kolkata":
        settings.timezone = d.timezone
        changed.append("timezone")
    if d.locale is not None and settings.locale == "en-IN":
        settings.locale = d.locale
        changed.append("locale")
    # Nullable text fields: apply only if NULL today.
    if d.ai_personality is not None and settings.ai_personality is None:
        settings.ai_personality = d.ai_personality
        changed.append("ai_personality")
    if d.ai_welcome_message is not None and settings.ai_welcome_message is None:
        settings.ai_welcome_message = d.ai_welcome_message
        changed.append("ai_welcome_message")

    if changed:
        await session.commit()
    report.defaults_applied.extend(changed)


__all__ = ["InstallReport", "install"]
