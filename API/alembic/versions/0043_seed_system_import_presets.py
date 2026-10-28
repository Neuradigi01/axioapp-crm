"""seed: system import presets — one per known source platform.

Data-only migration that inserts the default `{csv_column: crm_field_key}`
mappings for the five supported source platforms. Idempotent on
re-run: `ON CONFLICT DO NOTHING` against the unique
`(coalesce(org_id,...), source_platform, name)` index.

Mappings are best-effort starting points based on each platform's
default lead export shape. Real exports vary — Step 5's mapping UI
lets the user override every line. When customers report repeated
mis-mappings, ship a new seed migration that inserts an additional
"v2" system row rather than mutating the original (Owners who cloned
the original keep their copy).

`First Name + Last Name → contact.full_name (concat)` is intentionally
NOT modelled — v1 lacks a transform DSL. The HubSpot preset maps only
`First Name → contact.full_name`; users with separated names should
either pre-concat in their CSV or accept the first-name-only landing.

Revision ID: 0043_seed_system_import_presets
Revises: 0042_import_presets
Create Date: 2026-05-22 00:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op


revision: str = "0043_seed_system_import_presets"
down_revision: Union[str, None] = "0042_import_presets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Each entry: (name, source_platform, mapping_dict)
_SYSTEM_PRESETS: list[tuple[str, str, dict[str, str | None]]] = [
    (
        "Zoho CRM default",
        "zoho",
        {
            "Lead Name": "contact.full_name",
            "Email": "contact.email",
            "Phone": "contact.phone",
            "Mobile": "contact.phone",
            "Lead Source": "contact.source",
            "Annual Revenue": "lead.budget",
            "Lead Status": "lead.pipeline_stage",
        },
    ),
    (
        "HubSpot default",
        "hubspot",
        {
            "First Name": "contact.full_name",
            "Email": "contact.email",
            "Phone Number": "contact.phone",
            "Lifecycle Stage": "lead.pipeline_stage",
            "Amount": "lead.budget",
        },
    ),
    (
        "Salesforce default",
        "salesforce",
        {
            "Name": "contact.full_name",
            "Email": "contact.email",
            "Phone": "contact.phone",
            "Lead Status": "lead.pipeline_stage",
            "Annual Revenue": "lead.budget",
        },
    ),
    (
        "Freshsales default",
        "freshsales",
        {
            "Full Name": "contact.full_name",
            "Email": "contact.email",
            "Mobile": "contact.phone",
            "Lead Stage": "lead.pipeline_stage",
        },
    ),
    (
        "Generic CSV (empty)",
        "generic_csv",
        {},
    ),
]


def upgrade() -> None:
    for name, platform, mapping in _SYSTEM_PRESETS:
        op.execute(
            f"""
            INSERT INTO import_presets (org_id, source_platform, name, mapping, is_system)
            VALUES (NULL, '{platform}', {_sql_literal(name)}, {_sql_literal(json.dumps(mapping))}::jsonb, TRUE)
            ON CONFLICT (
                (COALESCE(org_id, '00000000-0000-0000-0000-000000000000'::uuid)),
                source_platform,
                name
            ) DO NOTHING
            """
        )


def downgrade() -> None:
    for _, platform, _ in _SYSTEM_PRESETS:
        op.execute(
            f"DELETE FROM import_presets WHERE is_system = TRUE AND source_platform = '{platform}'"
        )


def _sql_literal(value: str) -> str:
    """Single-quote a string for inline SQL. Escapes embedded quotes."""
    return "'" + value.replace("'", "''") + "'"
