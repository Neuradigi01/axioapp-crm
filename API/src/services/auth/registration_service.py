from config import CAPTCHA_TYPE
from src.app.shared.providers import captcha as captcha_provider
from src.constants import messages


async def verify_captcha_input(
    captcha_token: str | None, captcha_answer: str | None
) -> dict | None:
    """Validate captcha based on CAPTCHA_TYPE. Returns error dict or None if valid."""
    if CAPTCHA_TYPE == "image":
        if not captcha_token or not captcha_answer:
            return {"success": False, "message": messages.CAPTCHA_REQUIRED}
        if not captcha_provider.verify_captcha(captcha_token, captcha_answer):
            return {"success": False, "message": messages.INVALID_CAPTCHA}
    elif CAPTCHA_TYPE in ("recaptcha_v2", "recaptcha_v3"):
        if not captcha_token:
            return {"success": False, "message": messages.CAPTCHA_REQUIRED}
        if not await captcha_provider.verify_recaptcha(captcha_token):
            return {"success": False, "message": messages.INVALID_CAPTCHA}
    return None
