"""Email-sequences module descriptor.

Registers two permission keys with the core RBAC registry:

  * `email.sequences.manage` — authoring (Owner / Admin / Sales Manager).
  * `email.sequences.enroll`  — bulk enroll + pause / resume / cancel
    (Owner / Admin / Sales Manager / Employee — reps enroll their own
    leads into manager-built sequences).

No top-level sidebar entry — the sequences surface is the Settings →
Email Sequences tab in Step 11. `menu_position=None`.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="email_sequences",
    name="Email Sequences",
    icon="repeat",
    layer="core",
    route="/api/v1/email/sequences",
    frontend_route="/user/settings/email-sequences",
    menu_position=None,
    permissions=[
        "email.read",
        "email.sequences.manage",
        "email.sequences.enroll",
    ],
)
