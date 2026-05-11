from datetime import datetime
from sqlalchemy import BigInteger, Text, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from src.models import Base


class DeviceToken(Base):
    __tablename__ = 'tbl_device_tokens'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_type: Mapped[str] = mapped_column(Text, nullable=False)
    fcm_token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    device_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
