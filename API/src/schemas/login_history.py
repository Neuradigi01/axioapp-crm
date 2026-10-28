from pydantic import BaseModel, Field


class LoginHistoryListRequest(BaseModel):
    user_id: str = ""
    match_exact_user_id: bool = True
    page_index: int = Field(0, ge=0)
    page_size: int = Field(50, ge=1, le=200)


class LogoutSessionRequest(BaseModel):
    token_id: int = Field(..., gt=0)
