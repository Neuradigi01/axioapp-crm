import base64
import io

import pyotp
import pyqrcode

from config import APP_NAME


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def generate_qr_code(secret: str, user_id: str) -> str:
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user_id, issuer_name=APP_NAME)
    qr = pyqrcode.create(provisioning_uri)
    buffer = io.BytesIO()
    qr.png(buffer, scale=6)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def verify_totp_code(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
