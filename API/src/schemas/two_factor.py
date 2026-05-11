from pydantic import BaseModel, Field


class SendSetupOtpRequest(BaseModel):
    method: str = Field(..., pattern=r'^(email|sms)$')


class VerifyAndEnableRequest(BaseModel):
    code: str = Field(..., min_length=1)
    method: str = Field(..., pattern=r'^(authenticator|email|sms)$')


class ChangeMethodRequest(BaseModel):
    new_method: str = Field(..., pattern=r'^(authenticator|email|sms)$')
