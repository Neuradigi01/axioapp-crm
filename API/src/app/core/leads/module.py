"""Leads module descriptor.

Sidebar entry at `menu_position=250` (between Contacts at 200 and
Tasks at 300). Registers both permission keys at app startup.
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
    permissions=["leads.read", "leads.write", "leads.import"],
)
