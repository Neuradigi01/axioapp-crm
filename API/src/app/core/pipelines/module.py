"""Pipelines module descriptor.

`menu_position=None` — pipelines do not have a top-level sidebar entry
of their own. The kanban UI for each entity (Leads, Custom Orders, …)
embeds the pipeline visualisation; this module exists primarily to
expose the engine's read endpoints and to register the two permissions.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="pipelines",
    name="Pipelines",
    icon="kanban",
    layer="core",
    route="/api/v1/pipelines",
    frontend_route="/user/pipelines",
    menu_position=None,
    permissions=["pipelines.read", "pipelines.manage"],
)
