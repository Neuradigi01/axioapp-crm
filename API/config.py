import os
import base64
import hashlib
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

# --- ENC: prefix decryption ---
_MASTER_KEY = os.getenv("MASTER_KEY")
_fernet_instance = None

if _MASTER_KEY:
    _derived = hashlib.sha256(_MASTER_KEY.encode("utf-8")).digest()
    _fernet_instance = Fernet(base64.urlsafe_b64encode(_derived))


def _env(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key, default)
    if value and value.startswith("ENC:") and _fernet_instance:
        return _fernet_instance.decrypt(value[4:].encode("utf-8")).decode("utf-8")
    return value

COMPOSE_PROJECT_NAME = os.getenv("COMPOSE_PROJECT_NAME", "template_api")

# App
APP_NAME = os.getenv("APP_NAME", "Template App")

# Environment Flags
IS_DEVELOPMENT = os.getenv("IS_DEVELOPMENT", "false").lower() == "true"

# Captcha — "none" | "image" | "recaptcha_v2" | "recaptcha_v3"
CAPTCHA_TYPE = os.getenv("CAPTCHA_TYPE", "none").lower()
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "")
RECAPTCHA_SECRET_KEY = _env("RECAPTCHA_SECRET_KEY", "")

# IP Info
IPINFO_TOKEN = _env("IPINFO_TOKEN", "")

# Database
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = _env("DB_PASSWORD")

# JWT & Security Keys
JWT_SECRET_KEY = _env("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
FERNET_KEY = _env("FERNET_KEY", "default-fernet-key-change-this!!")

# Email
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_SENDER = os.getenv("EMAIL_SENDER", os.getenv("EMAIL_USER"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = _env("EMAIL_PASSWORD")
EMAIL_APP_PASSWORD = _env("EMAIL_APP_PASSWORD")
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))

# SMS
# OTP
OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", "10"))
ACTION_TOKEN_EXPIRY_MINUTES = int(os.getenv("ACTION_TOKEN_EXPIRY_MINUTES", "5"))

SMS_ENABLED = os.getenv("SMS_ENABLED", "false").lower() == "true"

# Contact Verification — "none" | "pre" | "post"
CONTACT_VERIFICATION_MODE = os.getenv("CONTACT_VERIFICATION_MODE", "none").lower()
SMS_API_URL = os.getenv("SMS_API_URL")
SMS_API_KEY = _env("SMS_API_KEY")

# Frontend URL (used in password reset emails, etc.)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4200")

# Logo URL (used in email templates — must be an absolute URL accessible externally)
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
LOGO_URL = os.getenv("LOGO_URL", f"{API_BASE_URL}/static/images/Logo.svg")

# Routes (API-internal cache only — Angular fetches routes via API endpoint)
ROUTES_API = os.getenv("ROUTES_API", "data/routes.json")

# Time
DATETIME_FORMAT = os.getenv("DATETIME_FORMAT", "%d-%b-%Y %I:%M:%S %p")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

# Static / Uploads
STATIC_DIR = os.getenv("STATIC_DIR", "./static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
MAX_ATTACHMENTS_PER_MESSAGE = int(os.getenv("MAX_ATTACHMENTS_PER_MESSAGE", "5"))

# Push Notifications (Firebase)
PUSH_NOTIFICATION_ENABLED = os.getenv("PUSH_NOTIFICATION_ENABLED", "false").lower() == "true"
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL", "")
FIREBASE_PRIVATE_KEY = _env("FIREBASE_PRIVATE_KEY", "")
FIREBASE_API_KEY = _env("FIREBASE_API_KEY", "")
FIREBASE_AUTH_DOMAIN = os.getenv("FIREBASE_AUTH_DOMAIN", "")
FIREBASE_MESSAGING_SENDER_ID = os.getenv("FIREBASE_MESSAGING_SENDER_ID", "")
FIREBASE_APP_ID = os.getenv("FIREBASE_APP_ID", "")
FIREBASE_VAPID_KEY = _env("FIREBASE_VAPID_KEY", "")

# Celery / Redis
CELERY_ENABLED = os.getenv("CELERY_ENABLED", "false").lower() == "true"
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB_BROKER = int(os.getenv("REDIS_DB_BROKER", "0"))
REDIS_DB_RESULT = int(os.getenv("REDIS_DB_RESULT", "1"))
REDIS_PASSWORD = _env("REDIS_PASSWORD", "")
