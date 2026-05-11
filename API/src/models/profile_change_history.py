from datetime import datetime
from sqlalchemy import BigInteger, Text, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from src.models import Base


class ProfileChangeHistory(Base):
    __tablename__ = 'tbl_profile_change_history'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_type: Mapped[str] = mapped_column(Text, nullable=False)
    old_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    new_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('idx_tbl_profile_change_history_member_id', 'member_id'),
        Index('idx_tbl_profile_change_history_user_type', 'user_type'),
    )
