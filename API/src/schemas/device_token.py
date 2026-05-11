from pydantic import BaseModel


class RegisterTokenRequest(BaseModel):
    fcm_token: str
    device_info: str | None = None


class UnregisterTokenRequest(BaseModel):
    fcm_token: str
