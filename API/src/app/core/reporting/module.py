"""Reporting module descriptor.

Owns the sidebar entry for the WhatsApp analytics dashboard
(whatsapp-platform-upgrade Step 20). Future reports — campaign
analytics, lead-funnel, sales-by-rep — will hang off the same
``/reports`` backend prefix + ``/user/reports`` frontend route
without needing a second descriptor.

Permission keys
---------------
``whatsapp.analytics.read`` gates every WhatsApp dashboard surface.
The legacy ``/reports/workload`` endpoint stays gated on
``users.read`` (it's the staff-workload sidebar tile inside Settings,
not a Reporting page) so it is intentionally **not** listed here.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="reporting",
    name="Reports",
    icon="bar-chart-3",
    layer="core",
    route="/api/v1/reports",
    frontend_route="/user/reports/whatsapp",
    # After Campaigns (560) and Reviews (570); before Settings (900).
    menu_position=600,
    permissions=[
        "whatsapp.analytics.read",
    ],
)
