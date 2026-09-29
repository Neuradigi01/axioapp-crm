"""Real-estate-pack Property module descriptor.

Auto-discovered at startup by the module-registry walker — no core
changes required (rule 5). Lives at the conventional path
`src.app.packs.<pack>.modules.<module>.module` that the walker
searches.

`layer='pack'` marks this as a Layer-2 module (not core). Property
takes ``menu_position=15`` so it slots between Dashboard (10) and
the Core CRM contact-side modules (typically 20+).
"""

from __future__ import annotations

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="property",
    name="Properties",
    icon="home",
    layer="pack",
    route="/api/v1/property",
    frontend_route="/user/properties",
    menu_position=210,
    permissions=[
        "property.read",
        "property.write",
        "property.publish",
        "property.archive",
        "property.delete",
    ],
    section="Sales",
    public_files=["{uuid}/property/{uuid}/*"],
)
