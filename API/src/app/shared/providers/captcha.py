from __future__ import annotations

import base64
import random
import string
import time
from io import BytesIO

import httpx
from captcha.image import ImageCaptcha

from config import RECAPTCHA_SECRET_KEY
from src.utilities.fernet_util import fernet

ALLOWED_CHARS = "".join(
    c for c in string.ascii_uppercase + string.digits if c not in "0OIl1"
)
CAPTCHA_LENGTH = 5
CAPTCHA_EXPIRY_SECONDS = 60
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


def generate_captcha() -> dict[str, str]:
    answer = "".join(random.choices(ALLOWED_CHARS, k=CAPTCHA_LENGTH))

    image_captcha = ImageCaptcha(width=280, height=90)
    image = image_captcha.generate_image(answer)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

    token = fernet.encrypt(f"{answer}|{int(time.time())}")
    return {"image": base64_image, "token": token}


def verify_captcha(token: str, answer: str) -> bool:
    try:
        decrypted = fernet.decrypt(token)
        parts = decrypted.split("|")
        if len(parts) != 2:
            return False

        original_answer, timestamp_str = parts
        if int(time.time()) - int(timestamp_str) > CAPTCHA_EXPIRY_SECONDS:
            return False

        return answer.strip().upper() == original_answer.upper()
    except Exception:
        return False


async def verify_recaptcha(token: str) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                RECAPTCHA_VERIFY_URL,
                data={"secret": RECAPTCHA_SECRET_KEY, "response": token},
            )
            return bool(response.json().get("success", False))
    except Exception:
        return False
