from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models import Base


class DeviceToken(Base):
    __tablename__ = "tbl_device_tokens"
    # Composite unique on (user_type, member_id, fcm_token). Was a
    # standalone unique on `fcm_token` alone — that let a caller who
    # obtained another user's FCM token re-register it under their own
    # account and silently hijack every push notification meant for the
    # original user (Register endpoint upserts by fcm_token).
    __table_args__ = (
        UniqueConstraint(
            "user_type",
            "member_id",
            "fcm_token",
            name="uq_device_tokens_user_token",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_type: Mapped[str] = mapped_column(Text, nullable=False)
    fcm_token: Mapped[str] = mapped_column(Text, nullable=False)
    device_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
