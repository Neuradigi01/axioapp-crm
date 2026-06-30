from pydantic import BaseModel, Field


class RouteSaveRequest(BaseModel):
    id: int | None = None
    parent_id: int = 0
    control_id: str = ""
    user_type: str = Field(..., pattern=r"^(Admin|User|Any)$")
    name: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    url: str = ""
    description: str = ""
    mat_icon: str = ""
    css_classes: str = ""
    is_nav_menu_item: bool = False
    order_no: int = 0
    nav_parent_id: int = 0
    is_compulsory: bool = False


class ToggleActiveRequest(BaseModel):
    route_ids: list[int]
    is_active: bool
