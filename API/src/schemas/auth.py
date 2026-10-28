from pydantic import BaseModel, EmailStr, Field


class DeviceInfo(BaseModel):
    browser: str | None = None
    browser_version: str | None = None
    device: str | None = None
    device_type: str | None = None
    os: str | None = None
    os_version: str | None = None
    user_agent: str | None = None


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    two_factor_code: str | None = None
    two_factor_method: str | None = Field(None, pattern=r"^(authenticator|email|sms)$")
    device_info: DeviceInfo | None = None
    captcha_token: str | None = None
    captcha_answer: str | None = None


class SendContactOtpRequest(BaseModel):
    type: str = Field(..., pattern=r"^(email|sms)$")
    value: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    password: str = Field(..., min_length=8)
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    email: EmailStr
    mobile_no: str | None = None
    country_id: int | None = None
    state_id: int | None = None
    referral_id: str | None = None
    captcha_token: str | None = None
    captcha_answer: str | None = None
    email_otp_token: str | None = None
    email_otp_code: str | None = None
    mobile_otp_token: str | None = None
    mobile_otp_code: str | None = None


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=1)


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(..., min_length=1)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class TwoFactorRequest(BaseModel):
    identifier: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    user_type: str = Field(..., pattern=r"^(User|Admin)$")
    method: str = Field(..., pattern=r"^(authenticator|email|sms)$")


class LoginResponse(BaseModel):
    success: bool
    message: str
    data: dict | None = None
