from datetime import datetime
from sqlalchemy import BigInteger, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from src.models import Base


class Ticket(Base):
    __tablename__ = 'tbl_tickets'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_no: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    from_member_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    from_user_type: Mapped[str] = mapped_column(Text, nullable=False)
    to_member_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    to_user_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default='Open')
    priority: Mapped[str] = mapped_column(Text, default='Normal')
    is_read_by_recipient: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    closed_by_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    replies: Mapped[list["TicketReply"]] = relationship("TicketReply", back_populates="ticket")
    attachments: Mapped[list["TicketAttachment"]] = relationship(
        "TicketAttachment", back_populates="ticket", primaryjoin="Ticket.id == TicketAttachment.ticket_id"
    )

    __table_args__ = (
        Index('idx_tbl_tickets_from_member_id', 'from_member_id'),
        Index('idx_tbl_tickets_to_member_id', 'to_member_id'),
        Index('idx_tbl_tickets_status', 'status'),
    )


class TicketReply(Base):
    __tablename__ = 'tbl_ticket_replies'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('tbl_tickets.id'), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    replied_by_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    replied_by_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="replies")
    attachments: Mapped[list["TicketAttachment"]] = relationship(
        "TicketAttachment", back_populates="reply", primaryjoin="TicketReply.id == TicketAttachment.reply_id"
    )

    __table_args__ = (
        Index('idx_tbl_ticket_replies_ticket_id', 'ticket_id'),
    )


class TicketAttachment(Base):
    __tablename__ = 'tbl_ticket_attachments'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('tbl_tickets.id'), nullable=True)
    reply_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('tbl_ticket_replies.id'), nullable=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    stored_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    ticket: Mapped["Ticket"] = relationship(
        "Ticket", back_populates="attachments", primaryjoin="TicketAttachment.ticket_id == Ticket.id"
    )
    reply: Mapped["TicketReply"] = relationship(
        "TicketReply", back_populates="attachments", primaryjoin="TicketAttachment.reply_id == TicketReply.id"
    )

    __table_args__ = (
        Index('idx_tbl_ticket_attachments_ticket_id', 'ticket_id'),
        Index('idx_tbl_ticket_attachments_reply_id', 'reply_id'),
    )
