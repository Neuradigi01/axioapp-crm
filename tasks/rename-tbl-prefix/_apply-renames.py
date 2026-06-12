"""One-shot rename script for the tbl_ prefix track (Step 2).

Walks api/src/app/{core,packs,shared}/**/*.py, applies the naming-map renames
to `__tablename__` strings and `ForeignKey("…")` strings, and writes back
only files where content actually changed. Preserves original line endings
(read/write with `newline=''`) so files that contain no matches are not
rewritten with normalised line endings.

The `users` shim, `tbl_user_login`, and `tbl_organization_members` are
excluded by not appearing in the renames dict.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RENAMES = {
    "activities": "tbl_activities",
    "appointments": "tbl_appointments",
    "attendance": "tbl_attendance",
    "audit_logs": "tbl_audit_logs",
    "auth_sessions": "tbl_auth_sessions",
    "calls": "tbl_calls",
    "call_outcomes": "tbl_call_outcomes",
    "call_transcripts": "tbl_call_transcripts",
    "campaigns": "tbl_campaigns",
    "campaign_messages": "tbl_campaign_messages",
    "catalog_items": "tbl_catalog_items",
    "contacts": "tbl_contacts",
    "contact_groups": "tbl_contact_groups",
    "contact_group_members": "tbl_contact_group_members",
    "contact_imports": "tbl_contact_imports",
    "conversations": "tbl_conversations",
    "custom_field_definitions": "tbl_custom_field_definitions",
    "demo_credentials": "tbl_demo_credentials",
    "email_accounts": "tbl_email_accounts",
    "email_message_clicks": "tbl_email_message_clicks",
    "email_message_opens": "tbl_email_message_opens",
    "email_sequence_enrollment_steps": "tbl_email_sequence_enrollment_steps",
    "email_sequence_enrollments": "tbl_email_sequence_enrollments",
    "email_sequence_steps": "tbl_email_sequence_steps",
    "email_sequences": "tbl_email_sequences",
    "email_templates": "tbl_email_templates",
    "embed_keys": "tbl_embed_keys",
    "embed_submissions": "tbl_embed_submissions",
    "import_presets": "tbl_import_presets",
    "integration_dlq": "tbl_integration_dlq",
    "integration_subscriptions": "tbl_integration_subscriptions",
    "integrations": "tbl_integrations",
    "invitations": "tbl_invitations",
    "invoice_lines": "tbl_invoice_lines",
    "invoices": "tbl_invoices",
    "lead_imports": "tbl_lead_imports",
    "lead_scoring_rules": "tbl_lead_scoring_rules",
    "lead_sources": "tbl_lead_sources",
    "leads": "tbl_leads",
    "messages": "tbl_messages",
    "meta_page_tokens": "tbl_meta_page_tokens",
    "notifications": "tbl_crm_notifications",
    "notification_preferences": "tbl_notification_preferences",
    "org_invoice_seq": "tbl_org_invoice_seq",
    "org_settings": "tbl_org_settings",
    "organizations": "tbl_organizations",
    "payments": "tbl_payments",
    "permissions": "tbl_permissions",
    "pipeline_stages": "tbl_pipeline_stages",
    "pipelines": "tbl_pipelines",
    "reviews": "tbl_reviews",
    "role_permissions": "tbl_role_permissions",
    "roles": "tbl_roles",
    "saved_views": "tbl_saved_views",
    "staff_profiles": "tbl_staff_profiles",
    "staff_sessions": "tbl_staff_sessions",
    "standard_field_overrides": "tbl_standard_field_overrides",
    "stripe_webhook_events": "tbl_stripe_webhook_events",
    "subscription_invoices": "tbl_subscription_invoices",
    "subscriptions": "tbl_subscriptions",
    "tasks": "tbl_tasks",
    "usage_counters": "tbl_usage_counters",
    "walk_ins": "tbl_walk_ins",
    "whatsapp_account_configs": "tbl_whatsapp_account_configs",
    "whatsapp_templates": "tbl_whatsapp_templates",
    "widget_configs": "tbl_widget_configs",
    "fp_warehouses": "tbl_fp_warehouses",
    "fp_inventory_items": "tbl_fp_inventory_items",
    "fp_inventory_movements": "tbl_fp_inventory_movements",
    "fp_inventory_alerts": "tbl_fp_inventory_alerts",
    "fp_field_visits": "tbl_fp_field_visits",
    "fp_field_visit_photos": "tbl_fp_field_visit_photos",
    "fp_custom_orders": "tbl_fp_custom_orders",
    "fp_custom_order_measurements": "tbl_fp_custom_order_measurements",
    "fp_custom_order_photos": "tbl_fp_custom_order_photos",
    "fp_custom_order_stages": "tbl_fp_custom_order_stages",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOTS = [
    REPO_ROOT / "API" / "src" / "app" / "core",
    REPO_ROOT / "API" / "src" / "app" / "packs",
    REPO_ROOT / "API" / "src" / "app" / "shared",
]

# Quote character class: " or '
QC = r"[\"']"

# Precompile patterns for speed.
_PATTERNS = []
for old, new in RENAMES.items():
    escaped = re.escape(old)
    _PATTERNS.append(
        (
            re.compile(rf"(__tablename__\s*=\s*{QC}){escaped}({QC})"),
            rf"\g<1>{new}\g<2>",
        )
    )
    _PATTERNS.append(
        (
            re.compile(rf"(ForeignKey\s*\(\s*{QC}){escaped}(\.[a-zA-Z_]+{QC})"),
            rf"\g<1>{new}\g<2>",
        )
    )


def process(path: Path) -> tuple[bool, int]:
    """Process one file. Returns (was_modified, total_substitutions)."""
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            content = f.read()
    except (UnicodeDecodeError, OSError):
        return (False, 0)

    original = content
    total = 0
    for pat, repl in _PATTERNS:
        content, n = pat.subn(repl, content)
        total += n
    if content != original:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        return (True, total)
    return (False, 0)


def main() -> int:
    modified_files: list[tuple[Path, int]] = []
    files_seen = 0
    for root in ROOTS:
        if not root.exists():
            print(f"SKIP missing root: {root}", file=sys.stderr)
            continue
        for path in root.rglob("*.py"):
            files_seen += 1
            ok, n = process(path)
            if ok:
                rel = path.relative_to(REPO_ROOT)
                modified_files.append((rel, n))
                print(f"MOD ({n:3d} subs) {rel.as_posix()}")
    print("---")
    print(f"Files scanned:      {files_seen}")
    print(f"Files modified:     {len(modified_files)}")
    print(f"Total substitutions: {sum(n for _, n in modified_files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
