"""Staff-portal auth surface — PIN login for the shop-floor tablet.

This module owns the staff-side JWT pool (`scope="staff"`,
`staff_sessions` table). It does NOT show up in the admin sidebar — no
ModuleDescriptor — because tablet UX is a separate route tree
(`/staff-portal/...`) reached without the admin app.
"""
from src.app.core.staff_portal.service import (
    list_pickable_users,
    login,
)

__all__ = ["list_pickable_users", "login"]
