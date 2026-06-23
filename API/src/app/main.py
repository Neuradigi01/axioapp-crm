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
# Bind the configured Celery app at API startup so @shared_task tasks
# (e.g. process_meta_lead, process_google_lead, campaign senders) route
# .delay() calls to the right Redis broker rather than Celery's default.
from src.celery.worker import celery as _celery_app  # noqa: F401
from src.routers import router as legacy_router
from src.providers.route_provider import generate_routes_json
from src.providers.firebase_provider import initialize_firebase
from src.providers.error_log_provider import log_error_to_db
from config import APP_NAME, STATIC_DIR, UPLOAD_DIR

from src.app.core.activities.router import router as activities_router
from src.app.core.appointments.router import router as appointments_router
from src.app.core.audit.router import router as audit_router
from src.app.core.calls.router import (
    calls_router,
    outcomes_router as call_outcomes_router,
)
from src.app.core.auth.router import router as auth_router
from src.app.core.campaigns.router import router as campaigns_router
from src.app.core.catalog.router import router as catalog_router
from src.app.core.contacts.router import router as contacts_router
from src.app.core.contacts.groups.router import router as contact_groups_router
from src.app.core.contacts.imports.router import router as contact_imports_router
from src.app.core.conversations.router import router as conversations_router
from src.app.core.custom_fields.router import router as custom_fields_router
from src.app.core.health.router import router as health_router
from src.app.core.embed.router import (
    public_router as embed_public_router,
    router as embed_keys_router,
)
from src.app.core.email.router import router as email_router
from src.app.core.email.tracking.router import router as email_tracking_router
from src.app.core.email_sequences.router import router as email_sequences_router
from src.app.core.email_templates.router import router as email_templates_router
from src.app.core.integrations.router import router as integrations_router
from src.app.core.integrations.whatsapp.templates_router import (
    router as whatsapp_templates_router,
)
from src.app.core.integrations.whatsapp.automation_router import (
    ai_settings_router as whatsapp_ai_settings_router,
    assignment_router as whatsapp_assignment_router,
    router as whatsapp_automation_router,
)
from src.app.core.leads.router import router as leads_router
from src.app.core.leads.imports.router import router as lead_imports_router
from src.app.core.notifications.router import router as notifications_router
from src.app.core.notifications.ws import ws_router as notifications_ws_router
from src.app.core.packs.router import router as packs_router
from src.app.core.pipelines.router import router as pipelines_router
from src.app.core.reviews.router import router as reviews_router
from src.app.core.saved_views.router import router as saved_views_router
from src.app.core.settings.router import router as settings_router
from src.app.core.staff.router import router as staff_router
from src.app.core.standard_fields.router import router as standard_fields_router
from src.app.core.staff_portal.router import router as staff_portal_router
from src.app.core.tasks.router import router as tasks_router
from src.app.core.walk_ins.router import router as walk_ins_router
# Layer-2 pack routers. `main.py` is the composition root and is
# allowed to import from `packs/` — `core/` modules cannot.
from src.app.packs.furniture.modules.inventory.router import (
    router as fp_inventory_router,
)
from src.app.packs.furniture.modules.custom_orders.router import (
    router as fp_custom_orders_router,
)
from src.app.packs.furniture.modules.field_ops.router import (
    router as fp_field_ops_router,
    staff_portal_router as fp_field_ops_staff_portal_router,
)
from src.app.core.billing.router import router as billing_router
from src.app.core.dev.router import router as dev_router
from src.app.core.subscriptions.router import router as plans_router
from src.app.core.subscriptions.webhooks.router import (
    router as stripe_webhooks_router,
)
from src.app.packs.furniture.modules.billing.router import (
    router as fp_pos_router,
)
# Import the pack's billing __init__ so its PDF renderer registers
# itself with `core.billing.pdf_registry` at startup.
import src.app.packs.furniture.modules.billing  # noqa: F401
from src.app.core.module_registry import discover_modules, registry
from src.app.core.modules_router import router as modules_router
from src.app.core.invitations.router import router as invitations_router
from src.app.core.permissions.router import (
    permissions_router,
    role_templates_router,
    roles_router,
)
from src.app.core.permissions.service import register_permissions
from src.app.core.dashboard.router import router as dashboard_router
from src.app.core.reporting.router import router as reporting_router
from src.app.core.tenants.router import router as ownership_router
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

    # Step 3.5.12 — WhatsApp no longer needs a startup adapter
    # registration. Outbound is per-org via `resolve_whatsapp_adapter`
    # (DB lookup); inbound is per-org via `find_org_by_phone_id` in
    # the webhook receiver. The conversations registry still holds
    # any non-WhatsApp adapter modules' factories registered at their
    # own import time.

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
# Order matters: Starlette's `add_middleware` puts the most recently
# added middleware OUTERMOST (it runs first on the request path). We
# want the request path to be:
#
#     TenantContextMiddleware  (sets RequestContext.org_id from JWT)
#       → SubscriptionStateMiddleware  (reads org_id, blocks writes on
#                                       read_only / past_due / archived /
#                                       cancelled subs)
#         → CORSMiddleware  (response-side header injection)
#           → route handler
#
# So `SubscriptionStateMiddleware` must be added BEFORE
# `TenantContextMiddleware` in code (which makes it INNER relative to
# the context-setter, so context is populated by the time it runs).
from src.app.core.subscriptions.middleware import SubscriptionStateMiddleware  # noqa: E402

app.add_middleware(SubscriptionStateMiddleware)
app.add_middleware(TenantContextMiddleware)

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Local storage mount — backs `StorageBackend.url()`. Inventory covers
# (and any future pack-uploaded blobs) live under `./storage/`.
_STORAGE_DIR = "./storage"
os.makedirs(_STORAGE_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=_STORAGE_DIR), name="files")

app.include_router(legacy_router)
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(roles_router, prefix="/api/v1")
app.include_router(permissions_router, prefix="/api/v1")
app.include_router(role_templates_router, prefix="/api/v1")
app.include_router(packs_router, prefix="/api/v1")
app.include_router(ownership_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(reporting_router, prefix="/api/v1")
app.include_router(invitations_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(custom_fields_router, prefix="/api/v1")
app.include_router(contacts_router, prefix="/api/v1")
app.include_router(contact_groups_router, prefix="/api/v1")
app.include_router(contact_imports_router, prefix="/api/v1")
app.include_router(activities_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(pipelines_router, prefix="/api/v1")
app.include_router(leads_router, prefix="/api/v1")
app.include_router(lead_imports_router, prefix="/api/v1")
app.include_router(embed_keys_router, prefix="/api/v1")
app.include_router(embed_public_router, prefix="/api/v1")
app.include_router(email_router, prefix="/api/v1")
app.include_router(email_templates_router, prefix="/api/v1")
app.include_router(email_sequences_router, prefix="/api/v1")
# Step 8 — public tracking endpoints (open pixel, click redirect,
# unsubscribe landing). Intentionally unauthenticated — the recipient's
# email client fetches them with no JWT. Rate limiting is inside the
# router (100 req/min/IP).
app.include_router(email_tracking_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
app.include_router(whatsapp_templates_router, prefix="/api/v1/integrations")
app.include_router(whatsapp_automation_router, prefix="/api/v1/integrations")
app.include_router(whatsapp_assignment_router, prefix="/api/v1/integrations")
app.include_router(whatsapp_ai_settings_router, prefix="/api/v1/integrations")
app.include_router(appointments_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(notifications_ws_router, prefix="/api/v1")
app.include_router(walk_ins_router, prefix="/api/v1")
app.include_router(catalog_router, prefix="/api/v1")
app.include_router(staff_router, prefix="/api/v1")
app.include_router(staff_portal_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(calls_router, prefix="/api/v1")
app.include_router(call_outcomes_router, prefix="/api/v1")
app.include_router(reviews_router, prefix="/api/v1")
app.include_router(campaigns_router, prefix="/api/v1")
app.include_router(saved_views_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(standard_fields_router, prefix="/api/v1")
app.include_router(fp_inventory_router, prefix="/api/v1")
app.include_router(fp_custom_orders_router, prefix="/api/v1")
app.include_router(fp_field_ops_router, prefix="/api/v1")
app.include_router(fp_field_ops_staff_portal_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")
app.include_router(fp_pos_router, prefix="/api/v1")
app.include_router(plans_router, prefix="/api/v1")
app.include_router(stripe_webhooks_router, prefix="/api/v1")

# Dev-only routes (test-login dropdown backing endpoint, etc). Mounted
# only when IS_DEVELOPMENT=true on the API container — production never
# resolves `/api/v1/_dev/*`.
if os.getenv("IS_DEVELOPMENT", "").lower() == "true":
    app.include_router(dev_router, prefix="/api/v1")
    logger.info("dev routes mounted at /api/v1/_dev/* (IS_DEVELOPMENT=true)")
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
