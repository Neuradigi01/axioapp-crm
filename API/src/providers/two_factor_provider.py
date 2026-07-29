import base64
import io

import pyotp
import pyqrcode
from cryptography.fernet import InvalidToken

from config import APP_NAME
from src.utilities.fernet_util import fernet


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def generate_qr_code(secret: str, user_id: str) -> str:
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user_id, issuer_name=APP_NAME)
    qr = pyqrcode.create(provisioning_uri)
    buffer = io.BytesIO()
    qr.png(buffer, scale=6)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def encrypt_totp_secret(secret: str) -> str:
    """Wrap a fresh TOTP secret in Fernet before it lands in the DB.

    Callers must persist the return value, not the raw ``secret``. All
    reads should go through :func:`_decrypt_totp_secret` (see
    :func:`verify_totp_code`), which transparently accepts historical
    plaintext rows written before 0170 ran."""
    return fernet.encrypt(secret)


def _decrypt_totp_secret(stored: str) -> str:
    """Return the plaintext TOTP seed for a stored value.

    ``stored`` may be Fernet-encrypted (all rows written on or after the
    encryption change) or plaintext base32 (rows that predate it). Fernet
    ciphertext is always base64url and contains ``==``/``.`` padding that
    a base32 secret never has, so decryption failure cleanly falls back
    to treating the value as plaintext — no schema migration required
    for the rollout."""
    try:
        return fernet.decrypt(stored)
    except (InvalidToken, ValueError):
        return stored


def verify_totp_code(secret: str, code: str) -> bool:
    plaintext = _decrypt_totp_secret(secret)
    totp = pyotp.TOTP(plaintext)
    return totp.verify(code, valid_window=1)
