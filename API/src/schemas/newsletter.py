from pydantic import BaseModel


class NewsletterRequest(BaseModel):
    email: str


class NewsletterListRequest(BaseModel):
    search: str = ""
    status: str = "all"  # "all", "subscribed", "unsubscribed"
    page_index: int = 0
    page_size: int = 10
