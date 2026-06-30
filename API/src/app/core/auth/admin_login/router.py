"""Admin-login surface for the layered auth tree.

The legacy template's admin panel uses a separate user pool
(`tbl_admin`) with its own credentials, role keys (`access_rights`),
and JWT shape (`user_id` text login handle + `token_id` bigint). None
of that fits FurnitureCRM's multi-tenant model, but the admin panel
itself is left untouched per CLAUDE.md's "features/admin/ UNTOUCHED"
rule. To keep `core/auth/` the single home for every auth endpoint
this URL is mounted here while reusing the legacy
`authenticate_admin` service — no logic duplication, just a URL alias
that survives the Phase 6 cleanup of the legacy router tree.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.shared.db import get_db
from src.schemas.auth import LoginRequest
from src.services.auth import login_service
from src.utilities.app_utils import extract_login_context

router = APIRouter(tags=["Auth — Admin"])


@router.post("/admin-login")
async def admin_login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ctx = await extract_login_context(request, req.device_info)
    return await login_service.authenticate_admin(
        db=db,
        identifier=req.identifier,
        password=req.password,
        two_factor_code=req.two_factor_code,
        two_factor_method=req.two_factor_method,
        captcha_token=req.captcha_token,
        captcha_answer=req.captcha_answer,
        **ctx,
    )
