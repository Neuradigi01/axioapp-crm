from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.models import Base


class Route(Base):
    __tablename__ = "tbl_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(Integer, default=0)
    control_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    user_type: Mapped[str] = mapped_column(Text, nullable=False, default="Any")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    mat_icon: Mapped[str] = mapped_column(Text, default="")
    css_classes: Mapped[str] = mapped_column(Text, default="")
    is_nav_menu_item: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    nav_parent_id: Mapped[int] = mapped_column(Integer, default=0)
    is_compulsory: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    admin_routes: Mapped[list["AdminRoute"]] = relationship("AdminRoute", back_populates="route")

    __table_args__ = (
        Index("idx_tbl_routes_user_type", "user_type"),
        Index("idx_tbl_routes_is_active", "is_active"),
    )


class AdminRoute(Base):
    __tablename__ = "tbl_admin_routes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(Integer, ForeignKey("tbl_admin.id"), nullable=False)
    route_id: Mapped[int] = mapped_column(Integer, ForeignKey("tbl_routes.id"), nullable=False)
    assigned_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    admin: Mapped["Admin"] = relationship("Admin", back_populates="admin_routes")
    route: Mapped["Route"] = relationship("Route", back_populates="admin_routes")

    __table_args__ = (
        Index("idx_tbl_admin_routes_admin_id", "admin_id"),
        Index("idx_tbl_admin_routes_route_id", "route_id"),
    )
