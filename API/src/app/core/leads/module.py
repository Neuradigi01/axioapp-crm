"""Leads module descriptor.

Sidebar entry at `menu_position=250` (between Contacts at 200 and
Tasks at 300). Registers permission keys at app startup.

`leads.own` (Step 6) is distinct from `leads.write`: an Admin can
edit any lead in the org (`leads.write`) but isn't necessarily a
candidate for round-robin assignment. Sales-rep roles get
`leads.own` to opt into the assignment pool; the lifespan-time
permission registration writes the key to the `permissions` table
so RBAC can grant/deny it per role.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="leads",
    name="Leads",
    icon="target",
    layer="core",
    route="/api/v1/leads",
    frontend_route="/user/leads",
    menu_position=250,
    permissions=[
        "leads.read",
        "leads.write",
        "leads.import",
        # Eligibility for round-robin assignment from any ingestion
        # channel (manual, bulk, widget, Google, Meta). Distinct from
        # `leads.write` so org admins who oversee but don't sell can
        # be excluded from the rotation.
        "leads.own",
        # Single + bulk transfer permission. Distinct from
        # `leads.write` because a junior sales rep can edit their own
        # leads but shouldn't be able to hand them off to a peer —
        # transfers are a management-level action.
        "leads.reassign",
    ],
)
