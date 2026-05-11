"""
Semantic constants for route IDs used by AccessGuard.

These map to the `id` column in `tbl_routes`. Using named constants
instead of magic numbers makes router files self-documenting.
"""


class RouteIds:
    # ── User routes ──────────────────────────────────────────────────
    USER_DASHBOARD = 12
    USER_PROFILE = 13
    USER_SECURITY = 14
    USER_CHANGE_PASSWORD = 15

    USER_NOTIFICATIONS = 17

    # ── Admin routes ─────────────────────────────────────────────────
    ADMIN_DASHBOARD = 20
    ADMIN_PROFILE = 21
    ADMIN_SECURITY = 22
    ADMIN_CHANGE_PASSWORD = 23

    ADMIN_NOTIFICATIONS = 25

    # ── Admin > User management ──────────────────────────────────────
    USER_LIST = 31
    USER_DETAIL = 32

    # ── Admin > Sub-admin management ─────────────────────────────────
    SUB_ADMIN_LIST = 40
    SUB_ADMIN_ADD = 41
    SUB_ADMIN_ACCESS_RIGHTS = 42
    SUB_ADMIN_EDIT = 43

    # ── User > Support ────────────────────────────────────────────────
    USER_SUPPORT = 50
    USER_SUPPORT_COMPOSE = 51
    USER_SUPPORT_TICKETS = 52
    USER_SUPPORT_VIEW_TICKET = 54

    # ── User > Login History ────────────────────────────────────────────
    USER_LOGIN_HISTORY = 16

    # ── Admin > Login History ───────────────────────────────────────────
    ADMIN_LOGIN_HISTORY = 24

    # ── Admin > Contact Us ────────────────────────────────────────────
    ADMIN_CONTACT_US = 70

    # ── Admin > News ─────────────────────────────────────────────────
    ADMIN_NEWS = 71

    # ── Admin > Popups ──────────────────────────────────────────────────
    ADMIN_POPUPS = 72

    # ── Admin > Newsletter ─────────────────────────────────────────────
    ADMIN_NEWSLETTER = 74

    # ── Admin > Setup (developer-only) ────────────────────────────────
    ADMIN_SETUP = 80
    ADMIN_SETUP_ROUTES = 81
    ADMIN_SETUP_ENCRYPTION = 82

    # ── Developer-only route IDs ──────────────────────────────────────
    # Routes that should only be accessible to admins with is_developer=True.
    # Used by _build_admin_access_rights to include/exclude from JWT tokens.
    DEVELOPER_ONLY = [ADMIN_SETUP, ADMIN_SETUP_ROUTES, ADMIN_SETUP_ENCRYPTION]

    # ── Admin > Support ───────────────────────────────────────────────
    ADMIN_SUPPORT = 60
    ADMIN_SUPPORT_COMPOSE = 61
    ADMIN_SUPPORT_TICKETS = 62
    ADMIN_SUPPORT_VIEW_TICKET = 64
