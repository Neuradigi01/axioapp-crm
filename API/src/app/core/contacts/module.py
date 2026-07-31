"""Contacts module descriptor.

Rule 5 of the master prompt: modules register themselves. The startup
sweep in `main.py`'s lifespan imports this `MODULE` constant, registers
the descriptor with the module registry, and also persists
`contacts.read` / `contacts.write` into the `permissions` table.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="contacts",
    name="Contacts",
    icon="users",
    layer="core",
    route="/api/v1/contacts",
    frontend_route="/user/contacts",
    menu_position=100,
    permissions=["contacts.read", "contacts.write", "contacts.reassign"],
    section="Customers",
)
