from fastapi import APIRouter

from .login import router as login_router
from .verify_2fa import router as verify_2fa_router
from .register import router as register_router
from .forgot_password import router as forgot_password_router
from .reset_password import router as reset_password_router
from .captcha import router as captcha_router
from .verify_contact import router as verify_contact_router

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

router.include_router(login_router)
router.include_router(verify_2fa_router)
router.include_router(register_router)
router.include_router(forgot_password_router)
router.include_router(reset_password_router)
router.include_router(captcha_router)
router.include_router(verify_contact_router)
