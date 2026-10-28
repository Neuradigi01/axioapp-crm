import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from src.core.logger import logger
from src.routers import router as api_router
from src.providers.route_provider import generate_routes_json
from src.providers.firebase_provider import initialize_firebase
from src.providers.error_log_provider import log_error_to_db
from config import APP_NAME, STATIC_DIR, UPLOAD_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting up...")
    await generate_routes_json()
    initialize_firebase()
    yield
    logger.info("Application shutting down...")


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

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(api_router)


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
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: FastAPIRequest, exc: RequestValidationError):
    errors = [f"{err['loc'][-1]}: {err['msg']}" for err in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"success": False, "message": "; ".join(errors)}
    )


@app.get("/")
async def root():
    return {"success": True, "message": "Template API is running"}
