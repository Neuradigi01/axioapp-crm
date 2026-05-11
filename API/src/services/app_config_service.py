from src.constants import messages
from config import (
    CAPTCHA_TYPE, EMAIL_ENABLED, SMS_ENABLED, CONTACT_VERIFICATION_MODE,
    PUSH_NOTIFICATION_ENABLED, FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN,
    FIREBASE_PROJECT_ID, FIREBASE_MESSAGING_SENDER_ID, FIREBASE_APP_ID,
    FIREBASE_VAPID_KEY,
)


def get_app_config() -> dict:
    return {
        "success": True,
        "message": messages.OK,
        "data": {
            "captcha_enabled": CAPTCHA_TYPE != "none",
            "email_enabled": EMAIL_ENABLED,
            "sms_enabled": SMS_ENABLED,
            "contact_verification_mode": CONTACT_VERIFICATION_MODE,
            "push_notification_enabled": PUSH_NOTIFICATION_ENABLED,
            "firebase_config": {
                "api_key": FIREBASE_API_KEY,
                "auth_domain": FIREBASE_AUTH_DOMAIN,
                "project_id": FIREBASE_PROJECT_ID,
                "messaging_sender_id": FIREBASE_MESSAGING_SENDER_ID,
                "app_id": FIREBASE_APP_ID,
                "vapid_key": FIREBASE_VAPID_KEY,
            } if PUSH_NOTIFICATION_ENABLED else None,
        },
    }
