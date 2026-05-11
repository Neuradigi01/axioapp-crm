from datetime import datetime
from sqlalchemy import BigInteger, Integer, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from src.models import Base


class Popup(Base):
    __tablename__ = 'tbl_popups'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=True)
    user_type: Mapped[str] = mapped_column(Text, nullable=False, server_default='All')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey('tbl_admin.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
