"""Rename every application table to the `tbl_` prefix convention.

Aligns the layered package (`src.app.core.*` + `src.app.packs.furniture.*`)
with the rule documented in `API/docs/DATABASE_RULES.md` and already used
by the legacy `src.models.*` package (~22 tables). After this migration:

  * every plain-named core table → `tbl_<old_name>`
  * every `fp_*` pack table → `tbl_fp_<old_name>` (Option A per
    `tasks/rename-tbl-prefix/naming-map.md` §10)
  * `notifications` → `tbl_crm_notifications` to avoid the collision
    with the legacy admin app's `tbl_notifications`

Behaviour preservation:

  * `op.rename_table` does NOT move RLS policies, FKs, or CHECK
    constraints — they ride along automatically because Postgres
    attaches them by table OID, not by name. Verified on PG 17.
  * The two custom policy NAMES on `import_presets` are renamed for
    cosmetic consistency (Phase B). The generic `org_isolation`
    policy name does not embed the table name and stays as-is.
  * Auto-named indexes / FK / CHECK constraints / sequences DO keep
    the old table name in their identifier. Phase C renames them.
  * Phase D paranoia assertion aborts the migration if any `tbl_*`
    table has RLS enabled but no policy attached.

Excluded:

  * `users` shim Table — metadata-only, physical `users` dropped by
    migration 0037. Two FK strings `ForeignKey("users.id")` in
    audit/auth/models.py are parked per naming-map.md §8.
  * `tbl_user_login`, `tbl_user_info`, `tbl_organization_members`
    already canonical from DR.6 / DR.7.
  * 22 legacy template tables in `src.models.*` — already `tbl_*`.

Reversible via `downgrade()`. Run `alembic downgrade -1` to restore
the pre-rename names; the schema afterwards is byte-equivalent.

Revision ID: 0087_rename_to_tbl_prefix
Revises: 0086_add_email_tracking
Create Date: 2026-06-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0087_rename_to_tbl_prefix"
down_revision: Union[str, None] = "0086_add_email_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Source of truth: tasks/rename-tbl-prefix/naming-map.md.
# 67 plain core tables + 10 fp_ pack tables = 77 renames.
# Ordered alphabetically (FK constraints follow the table by OID;
# rename order does not need to respect dependencies).
RENAMES: list[tuple[str, str]] = [
    ("activities", "tbl_activities"),
    ("appointments", "tbl_appointments"),
    ("attendance", "tbl_attendance"),
    ("audit_logs", "tbl_audit_logs"),
    ("auth_sessions", "tbl_auth_sessions"),
    ("call_outcomes", "tbl_call_outcomes"),
    ("call_transcripts", "tbl_call_transcripts"),
    ("calls", "tbl_calls"),
    ("campaign_messages", "tbl_campaign_messages"),
    ("campaigns", "tbl_campaigns"),
    ("catalog_items", "tbl_catalog_items"),
    ("contact_group_members", "tbl_contact_group_members"),
    ("contact_groups", "tbl_contact_groups"),
    ("contact_imports", "tbl_contact_imports"),
    ("contacts", "tbl_contacts"),
    ("conversations", "tbl_conversations"),
    ("custom_field_definitions", "tbl_custom_field_definitions"),
    ("demo_credentials", "tbl_demo_credentials"),
    ("email_accounts", "tbl_email_accounts"),
    ("email_message_clicks", "tbl_email_message_clicks"),
    ("email_message_opens", "tbl_email_message_opens"),
    ("email_sequence_enrollment_steps", "tbl_email_sequence_enrollment_steps"),
    ("email_sequence_enrollments", "tbl_email_sequence_enrollments"),
    ("email_sequence_steps", "tbl_email_sequence_steps"),
    ("email_sequences", "tbl_email_sequences"),
    ("email_templates", "tbl_email_templates"),
    ("embed_keys", "tbl_embed_keys"),
    ("embed_submissions", "tbl_embed_submissions"),
    ("import_presets", "tbl_import_presets"),
    ("integration_dlq", "tbl_integration_dlq"),
    ("integration_subscriptions", "tbl_integration_subscriptions"),
    ("integrations", "tbl_integrations"),
    ("invitations", "tbl_invitations"),
    ("invoice_lines", "tbl_invoice_lines"),
    ("invoices", "tbl_invoices"),
    ("lead_imports", "tbl_lead_imports"),
    ("lead_routing_state", "tbl_lead_routing_state"),
    ("lead_scoring_rules", "tbl_lead_scoring_rules"),
    ("lead_sources", "tbl_lead_sources"),
    ("leads", "tbl_leads"),
    ("messages", "tbl_messages"),
    ("meta_page_tokens", "tbl_meta_page_tokens"),
    ("notification_preferences", "tbl_notification_preferences"),
    ("notifications", "tbl_crm_notifications"),
    ("org_invoice_seq", "tbl_org_invoice_seq"),
    ("org_settings", "tbl_org_settings"),
    ("organizations", "tbl_organizations"),
    ("payments", "tbl_payments"),
    ("permissions", "tbl_permissions"),
    ("pipeline_stages", "tbl_pipeline_stages"),
    ("pipelines", "tbl_pipelines"),
    ("reviews", "tbl_reviews"),
    ("role_permissions", "tbl_role_permissions"),
    ("roles", "tbl_roles"),
    ("saved_views", "tbl_saved_views"),
    ("staff_profiles", "tbl_staff_profiles"),
    ("staff_sessions", "tbl_staff_sessions"),
    ("standard_field_overrides", "tbl_standard_field_overrides"),
    ("stripe_webhook_events", "tbl_stripe_webhook_events"),
    ("subscription_invoices", "tbl_subscription_invoices"),
    ("subscriptions", "tbl_subscriptions"),
    ("tasks", "tbl_tasks"),
    ("usage_counters", "tbl_usage_counters"),
    ("walk_ins", "tbl_walk_ins"),
    ("whatsapp_account_configs", "tbl_whatsapp_account_configs"),
    ("whatsapp_templates", "tbl_whatsapp_templates"),
    ("widget_configs", "tbl_widget_configs"),
    # Furniture pack — Option A: unify `fp_*` under `tbl_fp_*`.
    ("fp_custom_order_measurements", "tbl_fp_custom_order_measurements"),
    ("fp_custom_order_photos", "tbl_fp_custom_order_photos"),
    ("fp_custom_order_stages", "tbl_fp_custom_order_stages"),
    ("fp_custom_orders", "tbl_fp_custom_orders"),
    ("fp_field_visit_photos", "tbl_fp_field_visit_photos"),
    ("fp_field_visits", "tbl_fp_field_visits"),
    ("fp_inventory_alerts", "tbl_fp_inventory_alerts"),
    ("fp_inventory_items", "tbl_fp_inventory_items"),
    ("fp_inventory_movements", "tbl_fp_inventory_movements"),
    ("fp_warehouses", "tbl_fp_warehouses"),
]


# Custom RLS policies whose NAMES embed the old table name. Tuples are
# (table_after_rename, old_policy_name, new_policy_name).
# Generic `org_isolation` policies (the helper default) carry no table
# name in their policy name and don't need renaming.
CUSTOM_POLICY_RENAMES: list[tuple[str, str, str]] = [
    ("tbl_import_presets", "import_presets_read", "tbl_import_presets_read"),
    ("tbl_import_presets", "import_presets_write", "tbl_import_presets_write"),
]


def upgrade() -> None:
    bind = op.get_bind()

    # Phase A — rename tables.
    for old, new in RENAMES:
        op.rename_table(old, new)

    # Phase B — rename custom RLS policy names.
    for table, old_policy, new_policy in CUSTOM_POLICY_RENAMES:
        op.execute(
            f'ALTER POLICY "{old_policy}" ON "{table}" '
            f'RENAME TO "{new_policy}"'
        )

    # Phase C — rename auto-named indexes / FK / CHECK / sequences.
    for old, new in RENAMES:
        _rename_auto_objects(
            bind, current_table=new, old_prefix=old, new_prefix=new
        )

    # Phase D — paranoia. Abort if any RLS-enabled tbl_* table has
    # no policy attached. Defends against a silent cross-tenant leak.
    op.execute(
        """
        DO $$
        DECLARE
            offender record;
        BEGIN
            FOR offender IN
                SELECT t.tablename
                FROM pg_tables t
                WHERE t.tablename ~ '^tbl_'
                  AND t.rowsecurity = true
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_policies p
                      WHERE p.tablename = t.tablename
                  )
            LOOP
                RAISE EXCEPTION
                    'Renamed table % has RLS enabled but no policy attached',
                    offender.tablename;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Reverse Phase C — rename auto-named objects back.
    # Tables are still at `tbl_*` names; objects are named after them.
    for old, new in reversed(RENAMES):
        _rename_auto_objects(
            bind, current_table=new, old_prefix=new, new_prefix=old
        )

    # Reverse Phase B — rename policies back.
    for table, old_policy, new_policy in CUSTOM_POLICY_RENAMES:
        op.execute(
            f'ALTER POLICY "{new_policy}" ON "{table}" '
            f'RENAME TO "{old_policy}"'
        )

    # Reverse Phase A — rename tables back.
    for old, new in reversed(RENAMES):
        op.rename_table(new, old)


def _rename_auto_objects(
    bind, *, current_table: str, old_prefix: str, new_prefix: str
) -> None:
    """Rename every index, FK / CHECK constraint, and sequence on
    `current_table` whose identifier starts with `<old_prefix>_` or
    `ix_<old_prefix>_`. Swaps the matched prefix for `<new_prefix>_`.

    PK and UNIQUE constraint names are linked to their underlying
    indexes and are renamed automatically when the index is renamed,
    so they are NOT visited separately.
    """
    schema = bind.execute(sa.text("SELECT current_schema()")).scalar()
    old_under = f"{old_prefix}_"
    ix_old_under = f"ix_{old_prefix}_"

    # 1) Indexes (covers PK / UNIQUE auto-indexes too).
    idx_rows = bind.execute(
        sa.text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = :s "
            "AND (indexname ~ :p1 OR indexname ~ :p2)"
        ),
        {
            "s": schema,
            "p1": f"^{old_prefix}_",
            "p2": f"^ix_{old_prefix}_",
        },
    ).fetchall()
    for (idx_name,) in idx_rows:
        if idx_name.startswith(ix_old_under):
            new_name = f"ix_{new_prefix}_" + idx_name[len(ix_old_under):]
        elif idx_name.startswith(old_under):
            new_name = f"{new_prefix}_" + idx_name[len(old_under):]
        else:
            continue
        bind.execute(
            sa.text(f'ALTER INDEX "{idx_name}" RENAME TO "{new_name}"')
        )

    # 2) FK + CHECK constraints — independent of indexes.
    con_rows = bind.execute(
        sa.text(
            "SELECT c.conname FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = :t "
            "AND c.contype IN ('f', 'c') "
            "AND c.conname ~ :p"
        ),
        {"t": current_table, "p": f"^{old_prefix}_"},
    ).fetchall()
    for (con_name,) in con_rows:
        if con_name.startswith(old_under):
            new_name = f"{new_prefix}_" + con_name[len(old_under):]
            bind.execute(
                sa.text(
                    f'ALTER TABLE "{current_table}" '
                    f'RENAME CONSTRAINT "{con_name}" TO "{new_name}"'
                )
            )

    # 3) Sequences — standalone objects (e.g. SERIAL `*_id_seq`).
    seq_rows = bind.execute(
        sa.text(
            "SELECT c.relname FROM pg_class c "
            "WHERE c.relkind = 'S' AND c.relname ~ :p"
        ),
        {"p": f"^{old_prefix}_"},
    ).fetchall()
    for (seq_name,) in seq_rows:
        if seq_name.startswith(old_under):
            new_name = f"{new_prefix}_" + seq_name[len(old_under):]
            bind.execute(
                sa.text(
                    f'ALTER SEQUENCE "{seq_name}" RENAME TO "{new_name}"'
                )
            )
