from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models import Base


class PasswordChangeHistory(Base):
    __tablename__ = "tbl_password_change_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_type: Mapped[str] = mapped_column(Text, nullable=False)
    old_password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    new_password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_tbl_password_change_history_member_id", "member_id"),
        Index("idx_tbl_password_change_history_user_type", "user_type"),
    )
