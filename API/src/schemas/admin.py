from pydantic import BaseModel, Field


class UpdateAdminProfileRequest(BaseModel):
    email: str | None = None
    mobile_no: str | None = None


class SubAdminListRequest(BaseModel):
    search: str | None = None
    status: bool | None = None
    page_index: int = Field(0, ge=0)
    page_size: int = Field(10, ge=1, le=100)


class CreateSubAdminRequest(BaseModel):
    admin_user_id: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=1, max_length=100)
    email: str | None = None
    mobile_no: str | None = None
    route_ids: list[int] = Field(default_factory=list)


class UpdateSubAdminRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str | None = None
    mobile_no: str | None = None


class UpdateRoutesRequest(BaseModel):
    admin_id: str = Field(..., min_length=1)
    route_ids: list[int] = Field(default_factory=list)


class ToggleStatusRequest(BaseModel):
    admin_id: str = Field(..., min_length=1)
    is_active: bool


class UserListRequest(BaseModel):
    search: str | None = None
    status: bool | None = None
    date_from: str | None = None
    date_to: str | None = None
    page_index: int = Field(0, ge=0)
    page_size: int = Field(10, ge=1, le=100)


class ToggleUserStatusRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    is_active: bool


class AdminChangeUserPasswordRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
