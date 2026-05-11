from pydantic import BaseModel


class NotificationListRequest(BaseModel):
    page_index: int = 0
    page_size: int = 10
