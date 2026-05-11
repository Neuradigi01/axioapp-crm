from fastapi import APIRouter
from .two_factor import router as two_factor_router
from .change_password import router as change_password_router
from .action_verify import router as action_verify_router
from .login_history import router as login_history_router
from .device_tokens import router as device_tokens_router

router = APIRouter()

router.include_router(two_factor_router)
router.include_router(change_password_router)
router.include_router(action_verify_router)
router.include_router(login_history_router)
router.include_router(device_tokens_router)
