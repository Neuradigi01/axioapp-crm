"""Shared formatting utilities."""


def format_display_purpose(purpose: str) -> str:
    """Convert snake_case purpose string to a human-readable display label.

    Example: '2fa_setup' -> '2FA Setup'
    """
    return purpose.replace("_", " ").title().replace("2Fa", "2FA")


def mask_email(email: str) -> str:
    """Mask an email address for display. e.g. 'john@example.com' -> 'j***n@example.com'"""
    if not email or "@" not in email:
        return ""
    local, domain = email.rsplit("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


def mask_mobile(mobile: str) -> str:
    """Mask a mobile number for display. e.g. '+1234567890' -> '***7890'"""
    if not mobile or len(mobile) < 4:
        return ""
    return "***" + mobile[-4:]
