import firebase_admin
from firebase_admin import credentials, messaging
from src.core.logger import logger
from config import (
    PUSH_NOTIFICATION_ENABLED,
    FIREBASE_PROJECT_ID,
    FIREBASE_CLIENT_EMAIL,
    FIREBASE_PRIVATE_KEY,
)

_firebase_initialized: bool = False


def initialize_firebase() -> None:
    global _firebase_initialized

    if not PUSH_NOTIFICATION_ENABLED:
        logger.info("Push notifications are disabled")
        return

    if _firebase_initialized:
        return

    try:
        private_key = FIREBASE_PRIVATE_KEY.replace("\\n", "\n")
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": FIREBASE_PROJECT_ID,
            "client_email": FIREBASE_CLIENT_EMAIL,
            "private_key": private_key,
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        logger.info("Firebase initialized successfully")
    except Exception as e:
        logger.error(f"Firebase initialization failed: {e}")


def send_push_notification(token: str, title: str, message: str, data: dict | None = None) -> bool:
    if not PUSH_NOTIFICATION_ENABLED or not _firebase_initialized:
        return False

    try:
        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=message),
            token=token,
            data=data,
        )
        messaging.send(msg)
        return True
    except Exception as e:
        logger.error(f"Failed to send push notification: {e}")
        return False


def send_push_to_multiple(tokens: list[str], title: str, message: str, data: dict | None = None) -> list[str]:
    if not PUSH_NOTIFICATION_ENABLED or not _firebase_initialized:
        return []

    try:
        msg = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=message),
            tokens=tokens,
            data=data,
        )
        response = messaging.send_each_for_multicast(msg)
        failed_tokens = [
            tokens[i] for i, send_response in enumerate(response.responses)
            if not send_response.success
        ]
        if failed_tokens:
            logger.warning(f"Failed to send push to {len(failed_tokens)} token(s)")
        return failed_tokens
    except Exception as e:
        logger.error(f"Failed to send multicast push notification: {e}")
        return list(tokens)
