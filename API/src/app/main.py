"""FurnitureCRM FastAPI entry point.

Mounts:
  - Legacy template routers from `src.routers` at `/api/...`
    (auth, app-config, routes/config, common — preserves existing endpoints).
  - New layered routers under `/api/v1/...`
    (health for now; modules added in later steps).
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.core.logger import logger
from src.routers import router as legacy_router
from src.providers.route_provider import generate_routes_json
from src.providers.firebase_provider import initialize_firebase
from src.providers.error_log_provider import log_error_to_db
from config import APP_NAME, STATIC_DIR, UPLOAD_DIR

from src.app.core.activities.router import router as activities_router
from src.app.core.audit.router import router as audit_router
from src.app.core.auth.router import router as auth_router
from src.app.core.contacts.router import router as contacts_router
from src.app.core.custom_fields.router import router as custom_fields_router
from src.app.core.health.router import router as health_router
from src.app.core.pipelines.router import router as pipelines_router
from src.app.core.tasks.router import router as tasks_router
from src.app.core.module_registry import discover_modules, registry
from src.app.core.modules_router import router as modules_router
from src.app.core.permissions.service import register_permissions
from src.app.core.users.router import router as users_router
from src.app.shared.db import async_session
from src.app.shared.middleware import TenantContextMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FurnitureCRM API starting up...")
    await generate_routes_json()
    initialize_firebase()

    registry.clear()
    discover_modules()
    discovered_ids = [m.id for m in registry.list()]
    logger.info("discovered modules: %s", discovered_ids)

    all_permission_keys: list[str] = []
    for module in registry.list():
        all_permission_keys.extend(module.permissions)
    if all_permission_keys:
        async with async_session() as session:
            await register_permissions(session, all_permission_keys)

    yield
    logger.info("FurnitureCRM API shutting down...")


app = FastAPI(
    title=APP_NAME,
    default_response_class=JSONResponse,
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TenantContextMiddleware)

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(legacy_router)
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(custom_fields_router, prefix="/api/v1")
app.include_router(contacts_router, prefix="/api/v1")
app.include_router(activities_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(pipelines_router, prefix="/api/v1")
app.include_router(modules_router, prefix="/api/v1")


@app.middleware("http")
async def catch_exceptions_middleware(request: FastAPIRequest, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        error_message = await log_error_to_db(exc, request=request)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": error_message},
        )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: FastAPIRequest, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(
            status_code=exc.status_code, content=exc.detail, headers=exc.headers
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: FastAPIRequest, exc: RequestValidationError):
    errors = [f"{err['loc'][-1]}: {err['msg']}" for err in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"success": False, "message": "; ".join(errors)},
    )


@app.get("/")
async def root():
    return {"success": True, "message": "FurnitureCRM API is running"}
