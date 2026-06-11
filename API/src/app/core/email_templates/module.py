"""Email-templates module descriptor.

Registers `email.read` + `email.templates.manage` with the core
RBAC registry at startup. The templates surface is the Settings →
Email Templates tab in Step 10; no top-level sidebar entry, so
`menu_position=None`.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="email_templates",
    name="Email Templates",
    icon="file-text",
    layer="core",
    route="/api/v1/email/templates",
    frontend_route="/user/settings/email-templates",
    menu_position=None,
    permissions=[
        "email.read",
        "email.templates.manage",
    ],
)
