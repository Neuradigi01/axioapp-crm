"""Legacy URL: GET /api/auth/captcha.

The captcha implementation lives in `src.app.core.auth.captcha`. This
router preserves the legacy envelope response shape
(`{success, message, data}`) so the existing accounts/admin frontends
keep working until they migrate to `/api/v1/auth/captcha`.

No business logic here — just a backward-compatibility adapter.
"""
from fastapi import APIRouter

from src.app.core.auth.captcha import service as captcha_service
from src.constants import messages

router = APIRouter()


@router.get('/captcha')
async def get_captcha():
    challenge = captcha_service.issue_challenge()
    if challenge.type == "none":
        return {"success": False, "message": messages.CAPTCHA_DISABLED}
    if challenge.type in ("recaptcha_v2", "recaptcha_v3"):
        return {
            "success": True,
            "message": messages.OK,
            "data": {"type": challenge.type, "site_key": challenge.site_key},
        }
    return {
        "success": True,
        "message": messages.OK,
        "data": {"type": "image", "image": challenge.image, "token": challenge.token},
    }
