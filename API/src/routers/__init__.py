from fastapi import APIRouter

from src.routers.auth import router as auth_router
from src.routers.app_config import router as app_config_router
from src.routers.routes import router as routes_router
from src.routers.common import router as common_router

router = APIRouter(prefix="/api")

router.include_router(auth_router)
router.include_router(app_config_router)
router.include_router(routes_router)
router.include_router(common_router)
