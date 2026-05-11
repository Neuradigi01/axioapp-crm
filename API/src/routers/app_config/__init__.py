from fastapi import APIRouter

from .config import router as config_router

router = APIRouter(tags=["App Config"])

router.include_router(config_router)
