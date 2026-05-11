from fastapi import APIRouter

from src.routers.routes.config import router as config_router

router = APIRouter(prefix="/routes", tags=["Routes"])

router.include_router(config_router)
