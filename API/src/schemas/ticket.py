from pydantic import BaseModel, Field


class AttachmentItem(BaseModel):
    stored_name: str = Field(..., min_length=1)
    file_name: str = Field(..., min_length=1)
    file_size: int
    mime_type: str = Field(..., min_length=1)


class ComposeRequest(BaseModel):
    to_user_id: str | None = None
    subject: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    priority: str = "Normal"
    attachments: list[AttachmentItem] = []


class InboxRequest(BaseModel):
    status: str | None = None
    search_term: str | None = None
    priority: str | None = None
    from_user_id: str | None = None
    page_index: int = 0
    page_size: int = 10


class ReplyRequest(BaseModel):
    message: str = Field(..., min_length=1)
    attachments: list[AttachmentItem] = []


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., min_length=1)
