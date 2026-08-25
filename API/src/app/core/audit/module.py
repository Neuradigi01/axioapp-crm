"""Audit-log module descriptor.

Registers the "Audit Log" sidebar entry — Enterprise operators view
the full audit trail here. Recording happens on every plan (the
``audit.log(...)`` calls scattered across the codebase always write
into ``tbl_audit_logs``); the sidebar entry is visible whenever the
caller has the ``audit.read`` permission (Owner + Admin by default),
and the page itself renders a locked "Upgrade to Enterprise" card
when the plan doesn't grant ``audit.full_log``.

Placed under ``Business`` alongside ``Reports`` so both surfaces sit
together in the sidebar. ``menu_position=835`` puts it directly after
``Reports`` (830) and before ``Settings`` (900).
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="audit_log",
    name="Audit Log",
    icon="shield-check",
    layer="core",
    route="/api/v1/audit-logs",
    frontend_route="/user/reports/audit-log",
    menu_position=835,
    permissions=[
        "audit.read",
    ],
    section="Business",
)
