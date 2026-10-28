from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.models import Base


class UserLogin(Base):
    __tablename__ = "tbl_user_login"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    password: Mapped[str] = mapped_column(Text, nullable=False)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    two_factor_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    two_factor_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    user_info: Mapped["UserInfo"] = relationship(
        "UserInfo", back_populates="user_login", uselist=False
    )


class UserInfo(Base):
    __tablename__ = "tbl_user_info"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tbl_user_login.id"), nullable=False, unique=True
    )
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    mobile_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tbl_countries.id"), nullable=True
    )
    state_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tbl_states.id"), nullable=True
    )
    referral_id: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    profile_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_mobile_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    joining_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user_login: Mapped["UserLogin"] = relationship("UserLogin", back_populates="user_info")

    __table_args__ = (
        Index("idx_tbl_user_info_member_id", "member_id"),
        Index("idx_tbl_user_info_referral_id", "referral_id"),
    )
