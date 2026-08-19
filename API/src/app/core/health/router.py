from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends

from src.app.core.ai_assistants.models import JanitorHeartbeat
from src.app.shared.db import get_db

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@router.get("/health/janitor")
async def health_janitor(session: AsyncSession = Depends(get_db)) -> dict:
    """Return the janitor heartbeat status. External monitoring (Prometheus,
    etc.) checks if any task's ``last_run_at`` is older than 48 hours and
    alerts if the heartbeat stops."""
    stmt = select(JanitorHeartbeat).order_by(JanitorHeartbeat.name)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    heartbeats = [
        {
            "name": row.name,
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            "last_run_status": row.last_run_status,
            "last_error": row.last_error,
        }
        for row in rows
    ]

    return {
        "status": "ok",
        "heartbeats": heartbeats,
        "count": len(heartbeats),
    }
