from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from config import CAPTCHA_TYPE, RECAPTCHA_SITE_KEY
from src.app.shared.providers import captcha as captcha_provider


class CaptchaChallenge(BaseModel):
    type: Literal["image", "recaptcha_v2", "recaptcha_v3", "none"]
    image: str | None = None
    token: str | None = None
    site_key: str | None = None


def issue_challenge() -> CaptchaChallenge:
    if CAPTCHA_TYPE == "none":
        return CaptchaChallenge(type="none")
    if CAPTCHA_TYPE in ("recaptcha_v2", "recaptcha_v3"):
        return CaptchaChallenge(type=CAPTCHA_TYPE, site_key=RECAPTCHA_SITE_KEY)
    challenge = captcha_provider.generate_captcha()
    return CaptchaChallenge(type="image", image=challenge["image"], token=challenge["token"])
