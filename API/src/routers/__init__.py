from fastapi import APIRouter

from src.routers.app_config import router as app_config_router
from src.routers.common import router as common_router
from src.routers.location import router as location_router
from src.routers.routes import router as routes_router

router = APIRouter(prefix="/api")

router.include_router(app_config_router)
router.include_router(routes_router)
router.include_router(common_router)
router.include_router(location_router)
