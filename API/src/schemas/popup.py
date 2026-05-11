from pydantic import BaseModel


class PopupListRequest(BaseModel):
    status: str = "all"  # "all", "active", "inactive"
    user_type: str = "all"  # "all", "User", "Admin", "All"
    page_index: int = 0
    page_size: int = 10
