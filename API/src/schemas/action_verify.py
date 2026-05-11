from pydantic import BaseModel, Field


class VerifyActionRequest(BaseModel):
    code: str = Field(..., min_length=1)
    method: str = Field(..., pattern=r'^(authenticator|email|sms)$')


class SendActionVerifyOtpRequest(BaseModel):
    method: str = Field(..., pattern=r'^(email|sms)$')
