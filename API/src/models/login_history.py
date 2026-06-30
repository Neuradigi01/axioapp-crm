from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models import Base


class LoginHistory(Base):
    __tablename__ = "tbl_login_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_type: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str] = mapped_column(Text, default="")
    sender_ip: Mapped[str] = mapped_column(Text, default="")
    ip_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    device_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_valid_credentials: Mapped[bool] = mapped_column(Boolean, default=False)
    is_login_successful: Mapped[bool] = mapped_column(Boolean, default=False)
    is_token_active: Mapped[bool] = mapped_column(Boolean, default=False)
    logout_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    logout_remarks: Mapped[str] = mapped_column(Text, default="")
    logout_by_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    logout_by_type: Mapped[str] = mapped_column(Text, default="")
    by_admin_token_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("idx_tbl_login_history_user_id", "user_id"),
        Index("idx_tbl_login_history_is_token_active", "is_token_active"),
    )
