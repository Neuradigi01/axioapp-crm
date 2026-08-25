"""Audit-log HTTP routes.

  GET /api/v1/audit-logs?action=&entity_type=&user_id=&from=&to=&page=&size=
    → paginated JSON list of audit rows (gated on ``audit.full_log`` feature).

  GET /api/v1/audit-logs/export.csv?...same filters...
    → streaming CSV export (gated on ``audit.full_log`` feature).

Recording lives everywhere (all plans). Viewing is Enterprise-only:
the ``@requires_feature(FEATURE_AUDIT_FULL_LOG)`` decorator raises
HTTP 402 for lower plans so the frontend can render the standard
"Upgrade to Enterprise" locked-feature card without the raw rows
ever crossing the wire.

Both routes stack the plan gate on top of the ``audit.read`` RBAC
permission (typically granted to Owner + Admin). Auto-tenant ORM
filter restricts every query to the caller's org so an Enterprise
Owner viewing this can never see rows belonging to another tenant.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.audit.schemas import AuditLogOut, AuditLogPage
from src.app.core.audit.service import export_audit_logs, list_audit_logs
from src.app.core.auth.dependencies import require_permissions
from src.app.core.subscriptions.decorators import requires_feature
from src.app.core.subscriptions.feature_keys import FEATURE_AUDIT_FULL_LOG
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/audit-logs", tags=["Audit"])


@router.get("", response_model=AuditLogPage)
@requires_feature(FEATURE_AUDIT_FULL_LOG)
async def list_audit(
    action: str | None = None,
    entity_type: str | None = None,
    user_id: uuid.UUID | None = None,
    from_dt: datetime | None = Query(None, alias="from"),
    to_dt: datetime | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("audit.read")),
) -> AuditLogPage:
    items, total = await list_audit_logs(
        db,
        action=action,
        entity_type=entity_type,
        user_id=user_id,
        from_dt=from_dt,
        to_dt=to_dt,
        page=page,
        size=size,
    )
    return AuditLogPage(
        items=[AuditLogOut.model_validate(row) for row in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/export.csv")
@requires_feature(FEATURE_AUDIT_FULL_LOG)
async def export_audit_csv(
    action: str | None = None,
    entity_type: str | None = None,
    user_id: uuid.UUID | None = None,
    from_dt: datetime | None = Query(None, alias="from"),
    to_dt: datetime | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("audit.read")),
) -> StreamingResponse:
    """Streaming CSV export of the filtered audit trail. Reuses the
    same filters as the JSON list endpoint so an operator can preview
    in the UI and then export the same rows.

    Buffer-based rather than truly streaming: 50k rows × ~500 bytes =
    ~25 MB worst-case, comfortable in memory. If compliance-grade
    exports need larger sets, that moves to the async-job pattern
    (background task → email link when done) in the Compliance track.
    """
    rows = await export_audit_logs(
        db,
        action=action,
        entity_type=entity_type,
        user_id=user_id,
        from_dt=from_dt,
        to_dt=to_dt,
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "created_at",
            "user_id",
            "action",
            "entity_type",
            "entity_id",
            "ip",
            "user_agent",
            "before",
            "after",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                str(r.id),
                r.created_at.isoformat() if r.created_at else "",
                str(r.user_id) if r.user_id else "",
                r.action,
                r.entity_type or "",
                str(r.entity_id) if r.entity_id else "",
                r.ip or "",
                r.ua or "",
                # JSONB → JSON-encoded string in the cell so it round-trips
                # through Excel + spreadsheet importers cleanly.
                _dumps(r.before),
                _dumps(r.after),
            ]
        )

    filename = f"audit-log-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _dumps(value: object | None) -> str:
    """JSON-encode a JSONB cell for CSV output. ``None`` becomes empty
    string so Excel doesn't render the literal "null"."""
    if value is None:
        return ""
    import json

    return json.dumps(value, default=str, ensure_ascii=False)
