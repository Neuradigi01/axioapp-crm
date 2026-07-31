"""Conversations module descriptor.

Sidebar entry at `menu_position=500` (after Staff at 450, before
Reporting). Permission keys `conversations.read` / `conversations.write`
register on startup via the standard module-registry pickup.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="conversations",
    name="Conversations",
    icon="message-circle",
    layer="core",
    route="/api/v1/conversations",
    frontend_route="/user/conversations",
    menu_position=310,
    permissions=[
        "conversations.read",
        "conversations.write",
        # whatsapp-platform-upgrade Step 14 — gate for tag CRUD.
        # Assignment continues to use `conversations.write`; only
        # creating / editing / deleting the tag library requires the
        # manage key. Owner + Admin get it; Employee does not by
        # default (they assign existing tags but don't manage the set).
        "settings.conversations.manage",
    ],
    section="My Work",
)
