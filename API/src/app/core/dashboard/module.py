"""Dashboard module descriptor.

Rule 5 of the master prompt: modules register themselves. The startup
sweep in `main.py`'s lifespan walks `core/*/module.py`, registers this
descriptor, and the frontend sidebar picks it up from `/api/v1/modules`
on its next shell init.

`permissions=[]` makes Dashboard public — `list_for_user()` returns
modules with empty permission lists to every authenticated caller,
which is what we want for the landing page.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="dashboard",
    name="Dashboard",
    icon="layout-dashboard",
    layer="core",
    route="/api/v1/dashboard",
    frontend_route="/user/dashboard",
    menu_position=10,
    permissions=[],
    section="Overview",
)
