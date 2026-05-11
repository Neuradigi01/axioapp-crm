from fastapi import APIRouter
from src.providers import captcha_provider
from src.constants import messages
from config import CAPTCHA_TYPE, RECAPTCHA_SITE_KEY

router = APIRouter()


@router.get('/captcha')
async def get_captcha():
    if CAPTCHA_TYPE == "none":
        return {"success": False, "message": messages.CAPTCHA_DISABLED}

    if CAPTCHA_TYPE in ("recaptcha_v2", "recaptcha_v3"):
        return {
            "success": True,
            "message": messages.OK,
            "data": {"type": CAPTCHA_TYPE, "site_key": RECAPTCHA_SITE_KEY},
        }

    data = captcha_provider.generate_captcha()
    data["type"] = "image"
    return {"success": True, "message": messages.OK, "data": data}
