from src.utilities.app_utils import send_mail_async, render_email_template
from src.utilities.formatting import format_display_purpose
from config import FRONTEND_URL, OTP_EXPIRY_MINUTES


async def send_welcome_email(to_email: str, user_id: str, user_name: str = ""):
    html_body = render_email_template("welcome", {
        "user_id": user_id,
        "user_name": user_name or user_id,
        "frontend_url": FRONTEND_URL,
    })
    return await send_mail_async(to_email, "Welcome to the Platform", html_body)


async def send_password_reset_email(to_email: str, reset_token: str):
    reset_link = f"{FRONTEND_URL}/accounts/reset-password?token={reset_token}"
    html_body = render_email_template("password_reset", {
        "reset_link": reset_link,
    })
    return await send_mail_async(to_email, "Password Reset Request", html_body)


async def send_verification_email(to_email: str, verification_link: str, user_name: str = ""):
    html_body = render_email_template("email_verification", {
        "verification_link": verification_link,
        "user_name": user_name or "there",
    })
    return await send_mail_async(to_email, "Verify Your Email Address", html_body)


async def send_otp_email(to_email: str, otp_code: str, purpose: str):
    display_purpose = format_display_purpose(purpose)
    html_body = render_email_template("otp_verification", {
        "otp_code": otp_code,
        "purpose": display_purpose,
        "otp_expiry_minutes": str(OTP_EXPIRY_MINUTES),
    })
    return await send_mail_async(to_email, f"Verification Code - {display_purpose}", html_body)
