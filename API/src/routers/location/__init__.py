"""Location reference data — countries and states.

Public, unauthenticated endpoints serving reference data the signup
form's Country / State dropdowns need. The data lives in
`tbl_countries` (236 rows) and `tbl_states` (3,539 rows), seeded by
`scripts/seed_countries.py`. The data-access layer
(`src/data_access/location_da.py`) already exposes the queries; this
module just wires them through HTTP.

Response shape matches the rest of the legacy API
(`{success, message, data}`) so `IApiResponse<T>` on the Angular side
deserialises without special handling.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import messages
from src.core.db import get_db
from src.data_access.location_da import (
    get_all_countries,
    get_states_by_country,
)

router = APIRouter(prefix="/location", tags=["Location"])


@router.get("/countries")
async def list_countries(db: AsyncSession = Depends(get_db)) -> dict:
    countries = await get_all_countries(db)
    return {
        "success": True,
        "message": messages.OK,
        "data": [{"id": c.id, "name": c.name, "iso2": c.iso2} for c in countries],
    }


@router.get("/countries/{country_id}/states")
async def list_states(country_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    states = await get_states_by_country(db, country_id)
    return {
        "success": True,
        "message": messages.OK,
        "data": [{"id": s.id, "name": s.name, "code": s.code} for s in states],
    }
