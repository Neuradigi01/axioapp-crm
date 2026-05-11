from pydantic import BaseModel


class CreateNewsRequest(BaseModel):
    heading: str
    details: str
    priority: int = 0
    user_type: str = "All"  # "User", "Admin", "All"


class UpdateNewsRequest(BaseModel):
    heading: str
    details: str
    priority: int = 0
    user_type: str = "All"


class NewsListRequest(BaseModel):
    search: str = ""
    status: str = "all"  # "all", "active", "inactive"
    user_type: str = "all"  # "all", "User", "Admin", "All"
    page_index: int = 0
    page_size: int = 10
