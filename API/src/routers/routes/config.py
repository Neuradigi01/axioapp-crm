from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import ROUTES_API
from src.constants import messages
from src.utilities.app_utils import load_json

router = APIRouter()


@router.get("/config")
async def get_routes_config():
    routes_data = load_json(ROUTES_API)
    if routes_data is None:
        return JSONResponse(
            status_code=404,
            content={"success": False, "message": messages.ROUTES_CONFIG_NOT_FOUND},
        )
    return {"success": True, "message": messages.OK, "data": routes_data}
