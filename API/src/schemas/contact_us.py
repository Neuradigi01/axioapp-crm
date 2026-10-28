from pydantic import BaseModel


class ContactUsRequest(BaseModel):
    name: str
    email: str
    type: str
    subject: str
    message: str


class ContactUsListRequest(BaseModel):
    search: str = ""
    type: str = "all"
    page_index: int = 0
    page_size: int = 10
