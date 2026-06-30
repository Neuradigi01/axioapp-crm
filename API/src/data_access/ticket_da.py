from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.ticket import Ticket, TicketReply


async def get_open_ticket_count(db: AsyncSession, member_id: int, user_type: str) -> int:
    stmt = (
        select(func.count())
        .select_from(Ticket)
        .where(
            Ticket.from_member_id == member_id,
            Ticket.from_user_type == user_type,
            Ticket.status == "Open",
        )
    )
    return (await db.execute(stmt)).scalar()


async def get_total_count(db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(Ticket)
    return (await db.execute(stmt)).scalar()


async def get_total_count_by_status(db: AsyncSession, status: str) -> int:
    stmt = select(func.count()).select_from(Ticket).where(Ticket.status == status)
    return (await db.execute(stmt)).scalar()


async def get_next_ticket_no(db: AsyncSession) -> str:
    stmt = select(func.count()).select_from(Ticket)
    count = (await db.execute(stmt)).scalar()
    return f"TKT-{(count + 1):06d}"


async def get_ticket_by_id(db: AsyncSession, ticket_id: int) -> Ticket | None:
    stmt = (
        select(Ticket)
        .options(
            selectinload(Ticket.replies).selectinload(TicketReply.attachments),
            selectinload(Ticket.attachments),
        )
        .where(Ticket.id == ticket_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_tickets(
    db: AsyncSession,
    member_id: int,
    user_type: str,
    status: str | None,
    search_term: str | None,
    priority: str | None,
    from_member_id: int | None,
    page_index: int,
    page_size: int,
) -> tuple[list[Ticket], int]:
    # Admins see all tickets; users see only their own
    if user_type == "Admin":
        base = select(Ticket)
    else:
        base = select(Ticket).where(
            or_(
                Ticket.from_member_id == member_id,
                Ticket.to_member_id == member_id,
            )
        )

    if status:
        base = base.where(Ticket.status == status)

    if priority:
        base = base.where(Ticket.priority == priority)

    if from_member_id:
        base = base.where(Ticket.from_member_id == from_member_id)

    if search_term:
        term = f"%{search_term.strip().lower()}%"
        base = base.where(
            or_(
                func.lower(Ticket.subject).like(term),
                func.lower(Ticket.ticket_no).like(term),
            )
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar()

    items_stmt = (
        base.options(
            selectinload(Ticket.replies).selectinload(TicketReply.attachments),
            selectinload(Ticket.attachments),
        )
        .order_by(Ticket.updated_at.desc())
        .offset(page_index * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return items, total


async def mark_replies_as_read(db: AsyncSession, ticket_id: int, reader_type: str):
    """Mark all unread replies NOT sent by the reader's type as read."""
    stmt = (
        update(TicketReply)
        .where(
            TicketReply.ticket_id == ticket_id,
            TicketReply.is_read == False,
            TicketReply.replied_by_type != reader_type,
        )
        .values(is_read=True)
    )
    await db.execute(stmt)


async def mark_ticket_read_by_recipient(db: AsyncSession, ticket_id: int):
    stmt = update(Ticket).where(Ticket.id == ticket_id).values(is_read_by_recipient=True)
    await db.execute(stmt)


async def update_ticket_status(
    db: AsyncSession,
    ticket_id: int,
    status: str,
    closed_by_id: int | None = None,
    closed_by_type: str | None = None,
    closed_at=None,
):
    values = {"status": status}
    if closed_by_id is not None:
        values["closed_by_id"] = closed_by_id
    if closed_by_type is not None:
        values["closed_by_type"] = closed_by_type
    if closed_at is not None:
        values["closed_at"] = closed_at
    stmt = update(Ticket).where(Ticket.id == ticket_id).values(**values)
    await db.execute(stmt)
