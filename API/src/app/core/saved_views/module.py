"""Saved-views module descriptor.

Saved views are a personal productivity feature, not a privilege —
every authenticated user gets ``saved_views.use`` via the default
role templates. The descriptor registers exactly one permission key;
visibility / mutation rules are enforced in the service layer.

No sidebar entry: the saved-views menu is rendered inside the leads
toolbar (and, in future, the contacts / walk-ins toolbars) — there is
no top-level "Saved Views" navigation. ``menu_position=None`` keeps
the registry quiet about it.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="saved_views",
    name="Saved Views",
    icon="bookmark",
    layer="core",
    route="/api/v1/saved-views",
    frontend_route="/user/leads",
    menu_position=None,
    permissions=[
        "saved_views.use",
    ],
)
