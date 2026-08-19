"""FurnitureCRM FastAPI entry point.

Mounts:
  - Legacy template routers from `src.routers` at `/api/...`
    (auth, app-config, routes/config, common — preserves existing endpoints).
  - New layered routers under `/api/v1/...`
    (health for now; modules added in later steps).
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi import Request as FastAPIRequest
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# Side-effect import so the email_senders MODULE descriptor lands on
# the module registry before the lifespan permission-fanout sweep.
import src.app.core.email_senders.module  # noqa: F401

# tasks/workflows Step 1 — side-effect import so the five workflow
# tables register with `Base.metadata` before the FastAPI app's
# tables-create + Alembic autogenerate sweep run.
import src.app.core.workflows.models  # noqa: F401

# Side-effect import so the workflows MODULE descriptor lands on
# the module registry before the lifespan permission-fanout sweep.
import src.app.core.workflows.module  # noqa: F401

# tasks/chatbot-builder Step 3 — chatbots MODULE descriptor.
import src.app.core.chatbots.module  # noqa: F401

# tasks/ai-assistants Step 1 — side-effect import so the two BYOK
# tables (tbl_ai_provider_keys, tbl_org_ai_cost_budget) register with
# `Base.metadata` before the FastAPI app's tables-create + Alembic
# autogenerate sweep run.
import src.app.core.integrations.ai.models  # noqa: F401

# Import the pack's billing __init__ so its PDF renderer registers
# itself with `core.billing.pdf_registry` at startup.
import src.app.packs.furniture.modules.billing  # noqa: F401
from config import APP_NAME, STATIC_DIR, UPLOAD_DIR
from src.app.core.activities.router import router as activities_router
from src.app.core.appointments.router import router as appointments_router
from src.app.core.audit.router import router as audit_router
from src.app.core.auth.router import router as auth_router
from src.app.core.automation.router import router as automations_router
from src.app.core.automation.tracking import router as automation_tracking_router
from src.app.core.billing.router import router as billing_router
from src.app.core.calls.router import (
    calls_router,
)
from src.app.core.calls.router import (
    outcomes_router as call_outcomes_router,
)
from src.app.core.campaigns.router import router as campaigns_router
from src.app.core.catalog.router import router as catalog_router
from src.app.core.contacts.groups.router import router as contact_groups_router
from src.app.core.contacts.imports.router import router as contact_imports_router
from src.app.core.contacts.router import router as contacts_router
from src.app.core.conversations.router import router as conversations_router
from src.app.core.custom_fields.router import router as custom_fields_router
from src.app.core.dashboard.router import router as dashboard_router
from src.app.core.dev.router import router as dev_router
from src.app.core.email.router import router as email_router
from src.app.core.email.tracking.router import router as email_tracking_router
from src.app.core.email_sender_setup.router import router as email_sender_setup_router
from src.app.core.email_senders.router import router as email_senders_router
from src.app.core.email_sequences.router import router as email_sequences_router
from src.app.core.embed.router import (
    public_router as embed_public_router,
)
from src.app.core.embed.router import (
    router as embed_keys_router,
)
from src.app.core.health.router import router as health_router
from src.app.core.integrations.ai.router import router as integrations_ai_router
from src.app.core.integrations.router import router as integrations_router
from src.app.core.integrations.whatsapp.automation_router import (
    ai_settings_router as whatsapp_ai_settings_router,
)
from src.app.core.integrations.whatsapp.automation_router import (
    assignment_router as whatsapp_assignment_router,
)
from src.app.core.integrations.whatsapp.automation_router import (
    block_list_router as whatsapp_block_list_router,
)
from src.app.core.integrations.whatsapp.automation_router import (
    router as whatsapp_automation_router,
)
from src.app.core.integrations.whatsapp.flows_router import (
    router as whatsapp_flows_router,
)
from src.app.core.integrations.whatsapp.quick_links_router import (
    public_router as whatsapp_public_quick_links_router,
)
from src.app.core.integrations.whatsapp.quick_links_router import (
    router as whatsapp_quick_links_router,
)
from src.app.core.integrations.whatsapp.templates_router import (
    router as whatsapp_templates_router,
)
from src.app.core.invitations.router import router as invitations_router
from src.app.core.leads.imports.router import router as lead_imports_router
from src.app.core.leads.router import router as leads_router
from src.app.core.module_registry import discover_modules, registry
from src.app.core.modules_router import router as modules_router
from src.app.core.notifications.router import router as notifications_router
from src.app.core.notifications.ws import ws_router as notifications_ws_router
from src.app.core.packs.router import router as packs_router
from src.app.core.permissions.router import (
    permissions_router,
    role_templates_router,
    roles_router,
)
from src.app.core.permissions.service import register_permissions
from src.app.core.pipelines.router import router as pipelines_router
from src.app.core.reporting.router import router as reporting_router
from src.app.core.reviews.router import router as reviews_router
from src.app.core.saved_views.router import router as saved_views_router
from src.app.core.settings.router import router as settings_router
from src.app.core.staff.router import router as staff_router
from src.app.core.staff_portal.router import router as staff_portal_router
from src.app.core.standard_fields.router import router as standard_fields_router
from src.app.core.subscriptions.router import router as plans_router
from src.app.core.subscriptions.webhooks.router import (
    router as stripe_webhooks_router,
)
from src.app.core.tasks.router import router as tasks_router
from src.app.core.templates.router import router as templates_router
from src.app.core.tenants.router import (
    router as ownership_router,
)
from src.app.core.tenants.router import (
    send_rules_router,
)
from src.app.core.users.router import router as users_router
from src.app.core.walk_ins.router import router as walk_ins_router
from src.app.core.workflows.router import router as workflows_router
from src.app.core.workflows.router import schedules_router as workflow_schedules_router
from src.app.core.chatbots.router import router as chatbots_router
from src.app.core.chatbots.reply_router import router as chatbots_reply_router
from src.app.packs.furniture.modules.billing.router import (
    router as fp_pos_router,
)
from src.app.packs.furniture.modules.custom_orders.router import (
    router as fp_custom_orders_router,
)
from src.app.packs.furniture.modules.field_ops.router import (
    router as fp_field_ops_router,
)
from src.app.packs.furniture.modules.field_ops.router import (
    staff_portal_router as fp_field_ops_staff_portal_router,
)

# Layer-2 pack routers. `main.py` is the composition root and is
# allowed to import from `packs/` — `core/` modules cannot.
from src.app.packs.furniture.modules.inventory.router import (
    router as fp_inventory_router,
)
from src.app.packs.real_estate.modules.property.public_router import (
    router as rp_property_public_router,
)
from src.app.packs.real_estate.modules.property.router import (
    router as rp_property_router,
)
from src.app.shared.db import async_session
from src.app.shared.middleware import TenantContextMiddleware

# Bind the configured Celery app at API startup so @shared_task tasks
# (e.g. process_meta_lead, process_google_lead, campaign senders) route
# .delay() calls to the right Redis broker rather than Celery's default.
from src.celery.worker import celery as _celery_app  # noqa: F401
from src.core.logger import logger
from src.providers.error_log_provider import log_error_to_db
from src.providers.firebase_provider import initialize_firebase
from src.providers.route_provider import generate_routes_json
from src.routers import router as legacy_router


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


async def catch_exceptions_middleware(request: FastAPIRequest, call_next):
    """Last-resort handler: turn an unhandled exception into a 500 JSON
    body (and a row in the error log) instead of a dropped connection."""
    try:
        return await call_next(request)
    except Exception as exc:
        error_message = await log_error_to_db(exc, request=request)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": error_message},
        )


# Order matters: Starlette's `add_middleware` puts the most recently
# added middleware OUTERMOST (it runs first on the request path), so the
# registrations below read inside-out. The resulting request path is:
#
#     CORSMiddleware  (outermost — sees EVERY response on the way out)
#       → catch_exceptions_middleware  (unhandled exception → 500 JSON)
#         → TenantContextMiddleware  (sets RequestContext.org_id from JWT)
#           → SubscriptionStateMiddleware  (reads org_id, blocks writes on
#                                           read_only / past_due / archived /
#                                           cancelled subs)
#             → route handler
#
# CORS MUST be outermost. Middleware that short-circuits — the 402 from
# `SubscriptionStateMiddleware`, the 500 from `catch_exceptions_middleware`
# — builds its own response and never reaches the route, so nothing
# nested inside it can add headers afterwards. With CORS on the inside
# those responses shipped without `Access-Control-Allow-Origin`; the
# browser then blocked them and the SPA saw an opaque status-0 failure
# with no body, forcing every page to render its generic fallback copy
# ("Upload failed — check the file format") instead of the real reason
# ("Your trial has ended"). Only responses produced by the router or by
# an `@app.exception_handler` were ever visible to the browser.
#
# `SubscriptionStateMiddleware` is registered FIRST (innermost) so that
# `TenantContextMiddleware`, sitting outside it, has already populated
# `RequestContext.org_id` by the time it runs.
from src.app.core.subscriptions.middleware import SubscriptionStateMiddleware  # noqa: E402

app.add_middleware(SubscriptionStateMiddleware)
app.add_middleware(TenantContextMiddleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=catch_exceptions_middleware)
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
app.include_router(send_rules_router, prefix="/api/v1")
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
# Same ordering rule as contacts above: `/leads/import` must be matched
# before `leads_router`'s `/leads/{lead_id}`.
app.include_router(lead_imports_router, prefix="/api/v1")
app.include_router(leads_router, prefix="/api/v1")
app.include_router(embed_keys_router, prefix="/api/v1")
app.include_router(embed_public_router, prefix="/api/v1")
app.include_router(email_router, prefix="/api/v1")
app.include_router(email_sender_setup_router, prefix="/api/v1")
app.include_router(email_senders_router, prefix="/api/v1")
app.include_router(email_sequences_router, prefix="/api/v1")
# tasks/template-library Step 3 — central multi-channel template
# library (Email + WhatsApp + SMS + FB / IG / push). Step 10 dropped
# the legacy email_templates_router; sequences + the picker now
# render against the central tables.
app.include_router(templates_router, prefix="/api/v1")
# tasks/automation-engine Step 3 — single-event trigger engine.
# CRUD + run-history + event-type discovery under /api/v1/automations.
app.include_router(automations_router, prefix="/api/v1")
# tasks/automation-engine Step 14 — public open + click tracking
# endpoints. Tokens are HMAC-signed on (run_id, action) so external
# actors can't fabricate hits. No auth required; mail clients can't
# carry session cookies.
app.include_router(automation_tracking_router, prefix="/api/v1")
# tasks/workflows Step 3 — multi-step branching workflows. CRUD +
# status transitions + folder CRUD + clone under /api/v1/workflows.
# Engine + run-history endpoints land in Step 4; analytics +
# diagnostics in Step 19.
app.include_router(workflows_router, prefix="/api/v1")
# tasks/workflow-scheduling Step 3 — schedule CRUD hangs off its own
# top-level prefix (``/api/v1/schedules``) so /api/v1/schedules/{id} +
# /api/v1/schedules/preview don't collide with the workflows router's
# ``/{workflow_id}`` catch-all. The nested list/create routes
# (``/api/v1/workflows/{workflow_id}/schedules``) stay on
# ``workflows_router``.
app.include_router(workflow_schedules_router, prefix="/api/v1")
# tasks/chatbot-builder Step 3 — chatbots CRUD + versions +
# save-target picker. Trigger dispatch (Step 5) and test-fire
# (Step 6) mount later.
app.include_router(chatbots_router, prefix="/api/v1")

# tasks/chatbot-builder Step 11 — public signed-reply URL endpoints
# (``/r/{sig}`` GET + POST). Deliberately unauthenticated — the
# customer clicks these from an email client. Mounted at ROOT (not
# ``/api/v1``) so email URLs stay short + memorable, and so mail-
# client link scanners don't strip a versioned API path.
app.include_router(chatbots_reply_router)
# Step 8 — public tracking endpoints (open pixel, click redirect,
# unsubscribe landing). Intentionally unauthenticated — the recipient's
# email client fetches them with no JWT. Rate limiting is inside the
# router (100 req/min/IP).
app.include_router(email_tracking_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
# tasks/ai-assistants Step 1 — BYOK OpenAI provider-key store +
# per-org daily/monthly USD budget cap. Sub-module of
# ``core/integrations/`` so future AI-provider consumers (workflow AI
# nodes, chatbot AI steps, campaign-copy assist) pick a stored key
# by id via ``shared.llm.factory(...)``. Gated on ``ai_providers.manage``.
app.include_router(integrations_ai_router, prefix="/api/v1")
app.include_router(whatsapp_templates_router, prefix="/api/v1/integrations")
app.include_router(whatsapp_automation_router, prefix="/api/v1/integrations")
app.include_router(whatsapp_assignment_router, prefix="/api/v1/integrations")
app.include_router(whatsapp_ai_settings_router, prefix="/api/v1/integrations")
app.include_router(whatsapp_block_list_router, prefix="/api/v1/integrations")
app.include_router(whatsapp_flows_router, prefix="/api/v1/integrations")
app.include_router(whatsapp_quick_links_router, prefix="/api/v1/integrations")
# Step 26 — public 302 redirect mounted at the app root (no version
# prefix). This is the URL the QR code encodes + the wa.me short
# link humans share offline.
app.include_router(whatsapp_public_quick_links_router)
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
app.include_router(rp_property_router, prefix="/api/v1")
app.include_router(rp_property_public_router, prefix="/api")
app.include_router(plans_router, prefix="/api/v1")
app.include_router(stripe_webhooks_router, prefix="/api/v1")

# Dev-only routes (test-login dropdown backing endpoint, etc). Mounted
# only when IS_DEVELOPMENT=true on the API container — production never
# resolves `/api/v1/_dev/*`.
if os.getenv("IS_DEVELOPMENT", "").lower() == "true":
    app.include_router(dev_router, prefix="/api/v1")
    logger.info("dev routes mounted at /api/v1/_dev/* (IS_DEVELOPMENT=true)")
app.include_router(modules_router, prefix="/api/v1")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: FastAPIRequest, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=exc.headers)
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
