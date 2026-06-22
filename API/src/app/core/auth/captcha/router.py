from fastapi import APIRouter

from src.app.core.auth.captcha.service import CaptchaChallenge, issue_challenge

router = APIRouter(prefix="/captcha", tags=["Auth — Captcha"])


@router.get("", response_model=CaptchaChallenge)
async def get_captcha() -> CaptchaChallenge:
    return issue_challenge()
