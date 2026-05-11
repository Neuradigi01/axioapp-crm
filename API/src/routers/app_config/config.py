from fastapi import APIRouter
from src.services import app_config_service

router = APIRouter()


@router.get("/app-config")
async def get_app_config():
    return app_config_service.get_app_config()
