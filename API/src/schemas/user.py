from pydantic import BaseModel, Field


class UpdateProfileRequest(BaseModel):
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    mobile_no: str | None = None
    country_id: int | None = None
    state_id: int | None = None


