from config import OTP_EXPIRY_MINUTES
from src.utilities.app_utils import send_sms_async
from src.utilities.formatting import format_display_purpose


async def send_otp_sms(mobile_no: str, otp_code: str, purpose: str):
    display_purpose = format_display_purpose(purpose)
    message = f"Your OTP code for {display_purpose} is: {otp_code}. It will expire in {OTP_EXPIRY_MINUTES} minutes."
    return await send_sms_async(mobile_no, message)
