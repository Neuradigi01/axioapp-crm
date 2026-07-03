import os
from pathlib import Path
from dotenv import load_dotenv

# Non-secret configuration is read from config.env (committed in plaintext).
# Secrets (DB_PASSWORD, JWT_SECRET_KEY, FERNET_KEY, ...) live in
# secrets.enc.env (SOPS + age encrypted) and are injected into the process
# environment at runtime by `sops exec-env` (see run.cmd / run.sh). Both
# config and secrets are then read uniformly via os.getenv — there is no
# plaintext secrets file on disk and no in-app decryption.
_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR / "config.env")

COMPOSE_PROJECT_NAME = os.getenv("COMPOSE_PROJECT_NAME", "template_api")

# App
APP_NAME = os.getenv("APP_NAME", "Template App")

# Environment Flags
IS_DEVELOPMENT = os.getenv("IS_DEVELOPMENT", "false").lower() == "true"

# Captcha — "none" | "image" | "recaptcha_v2" | "recaptcha_v3"
CAPTCHA_TYPE = os.getenv("CAPTCHA_TYPE", "none").lower()
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "")

# IP Info
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN", "")

# Database
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# JWT & Security Keys
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
FERNET_KEY = os.getenv("FERNET_KEY", "default-fernet-key-change-this!!")

# Email
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_SENDER = os.getenv("EMAIL_SENDER", os.getenv("EMAIL_USER"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))

# SMS
# OTP
OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", "10"))
ACTION_TOKEN_EXPIRY_MINUTES = int(os.getenv("ACTION_TOKEN_EXPIRY_MINUTES", "5"))

SMS_ENABLED = os.getenv("SMS_ENABLED", "false").lower() == "true"

# Contact Verification — "none" | "pre" | "post"
CONTACT_VERIFICATION_MODE = os.getenv("CONTACT_VERIFICATION_MODE", "none").lower()
SMS_API_URL = os.getenv("SMS_API_URL")
SMS_API_KEY = os.getenv("SMS_API_KEY")

# Frontend URL (used in password reset emails, etc.)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4200")

# Logo URL (used in email templates — must be an absolute URL accessible externally)
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
LOGO_URL = os.getenv("LOGO_URL", f"{API_BASE_URL}/static/images/Logo.svg")

# Routes (API-internal cache only — Angular fetches routes via API endpoint)
ROUTES_API = os.getenv("ROUTES_API", "data/routes.json")

# Time
DATETIME_FORMAT = os.getenv("DATETIME_FORMAT", "%d-%b-%Y %I:%M:%S %p")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

# Static / Uploads
STATIC_DIR = os.getenv("STATIC_DIR", "./static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
MAX_ATTACHMENTS_PER_MESSAGE = int(os.getenv("MAX_ATTACHMENTS_PER_MESSAGE", "5"))

# Push Notifications (Firebase)
PUSH_NOTIFICATION_ENABLED = os.getenv("PUSH_NOTIFICATION_ENABLED", "false").lower() == "true"
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL", "")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY", "")
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY", "")
FIREBASE_AUTH_DOMAIN = os.getenv("FIREBASE_AUTH_DOMAIN", "")
FIREBASE_MESSAGING_SENDER_ID = os.getenv("FIREBASE_MESSAGING_SENDER_ID", "")
FIREBASE_APP_ID = os.getenv("FIREBASE_APP_ID", "")
FIREBASE_VAPID_KEY = os.getenv("FIREBASE_VAPID_KEY", "")

# WhatsApp Business Cloud API
# Per-org credentials (access token, phone_id, waba_id) live in the
# `integrations` + `whatsapp_account_configs` tables (Step 3.5.12) —
# each org connects via Settings → Integrations → WhatsApp.
#
# Platform-level config (one Meta App + one Embedded Signup
# Configuration fronts all customers, Intercom / HubSpot pattern) lives
# below. Added by whatsapp-platform-upgrade Step 1.
#
# Embedded Signup Configuration ID — created in Meta App Dashboard →
# WhatsApp → Configurations. Frontend reads via
# `GET /api/v1/integrations/whatsapp/embedded-signup/config` (Step 3)
# and passes to `FB.login({ config_id })`. We configure it with
# `phone_number_selection=existing_only` so the popup never offers
# virtual-number / display-name-only paths (we are NOT a BSP).
WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID = os.getenv("WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", "")
# Graph API version pin for WhatsApp Cloud API calls. Defaults to
# v19.0 to match META_GRAPH_API_VERSION (same Meta App, same pin).
WHATSAPP_GRAPH_API_VERSION = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v19.0")
# Meta App secret — used for X-Hub-Signature-256 verification on
# inbound WhatsApp webhooks. Orgs connected via Embedded Signup
# (whatsapp-platform-upgrade Step 2) share this single platform-level
# secret because the Meta App IS the platform. Orgs that connected
# via the legacy manual flow keep their per-org `app_secret_enc`;
# the webhook verifier prefers this env var and falls back to the
# per-org row only when this is empty.
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")

# WhatsApp Web (unofficial / Baileys) — Step 4 of the
# `tasks/whatsapp-unofficial/` track. The Node sidecar at
# `sidecars/whatsapp-web/` owns the WhatsApp Web protocol; FastAPI
# speaks to it over HMAC-signed HTTP.
#
# SIDECAR_URL is the base URL FastAPI POSTs to (e.g. /sessions,
# /sessions/{id}/send-text, /sessions/{id}/download-media). Default
# is the docker-compose service name on the project network; local
# dev override via `http://localhost:4000`.
WHATSAPP_WEB_SIDECAR_URL = os.getenv(
    "WHATSAPP_WEB_SIDECAR_URL", "http://whatsapp-web-sidecar:4000"
)
# Outbound HMAC secret — used by the FastAPI client to sign every
# request to the sidecar. MUST match the sidecar's
# `SIDECAR_HMAC_SECRET`. Generate with:
#   python -c "import secrets; print(secrets.token_hex(32))"
# Stored in secrets.enc.env, NOT here.
WHATSAPP_WEB_SIDECAR_HMAC_SECRET = os.getenv(
    "WHATSAPP_WEB_SIDECAR_HMAC_SECRET", ""
)
# Inbound HMAC secret — used by the FastAPI events receiver
# (Step 6) to verify the sidecar's signature on every event POST.
# MUST match the sidecar's `FASTAPI_HMAC_SECRET`. Stored in
# secrets.enc.env, NOT here.
WHATSAPP_WEB_INBOUND_HMAC_SECRET = os.getenv(
    "WHATSAPP_WEB_INBOUND_HMAC_SECRET", ""
)

# Ad integrations (Google Ads + Meta Ads) — OAuth-token encryption.
# Fernet key — 32 url-safe-base64-encoded bytes. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Every access_token / refresh_token in the `integrations` table is
# encrypted with this key. Losing the key = every org must reconnect.
# Required for `core/integrations/*` to import; the module raises a
# clear RuntimeError at startup if the key is missing or malformed.
INTEGRATIONS_ENCRYPTION_KEY = os.getenv("INTEGRATIONS_ENCRYPTION_KEY", "")

# Fernet key for Real Estate pack's public property-link tokens
# (`packs/real_estate/modules/property/link_token.py`). Generate via
#   docker exec crm-api-1 python -c \
#     "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# then add to secrets.enc.env via `run secrets-edit`. Lazy-built at
# first use; the app boots without it but public-URL endpoints fail
# with a clear "not configured" message until the key is set.
PROPERTY_LINK_ENCRYPTION_KEY = os.getenv("PROPERTY_LINK_ENCRYPTION_KEY", "")

# Google Ads OAuth — Track 4 Step 2.
# Provision these from Google Cloud Console; see
# tasks/ad-integrations/manual-google-oauth-setup.md for full walkthrough.
# Dev mode (test users only) doesn't need verification — works today.
# The Developer Token requires a 1-5 day approval from Google.
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI",
    "http://localhost:8000/api/v1/integrations/google/callback",
)
# Gmail uses the SAME OAuth client (same `GOOGLE_OAUTH_CLIENT_ID` /
# `GOOGLE_OAUTH_CLIENT_SECRET`) but a separate redirect URI so the
# callback path is unambiguous. The Gmail consent screen requests
# different scopes (gmail.modify) than the Ads flow (adwords).
GOOGLE_GMAIL_REDIRECT_URI = os.getenv(
    "GOOGLE_GMAIL_REDIRECT_URI",
    "http://localhost:8000/api/v1/email/gmail/callback",
)
# tasks/google-calendar-sync Step 2 — per-user Google Calendar sync.
# Shares the same OAuth client as Ads / Gmail (one GOOGLE_OAUTH_CLIENT_ID /
# _SECRET pair) but a distinct callback path so the callback handler is
# unambiguous. The consent screen requests calendar.events scope + the
# usual openid/email/profile so we can populate the token row's
# google_email + google_user_id. Register this exact URI in Google
# Cloud Console → Credentials → OAuth 2.0 Client → Authorized redirect
# URIs (see manual-google-calendar-setup.md in the track folder).
GOOGLE_CALENDAR_REDIRECT_URI = os.getenv(
    "GOOGLE_CALENDAR_REDIRECT_URI",
    "http://localhost:30007/api/v1/integrations/google-calendar/callback",
)
# Gmail push notifications — fully-qualified Pub/Sub topic name
# (e.g. `projects/your-gcp-project/topics/gmail-events`). Optional.
# When unset, Step 2's connect flow skips the `users.watch` call and
# the mailbox is synced via Step 4's 60-second poll fallback.
GOOGLE_GMAIL_PUBSUB_TOPIC = os.getenv("GOOGLE_GMAIL_PUBSUB_TOPIC", "")
# Email address of the Pub/Sub-push service account configured to
# invoke our webhook. The push handler verifies the inbound OIDC JWT
# was signed by this identity. Required when the topic is set.
GOOGLE_GMAIL_PUBSUB_SA_EMAIL = os.getenv("GOOGLE_GMAIL_PUBSUB_SA_EMAIL", "")

# Microsoft 365 / Outlook OAuth (Track app-updates/email Step 3).
# Provision from an Azure App Registration. Multi-tenant works with
# `common`; single-tenant uses the tenant id. Reuses the same
# Fernet token storage (INTEGRATIONS_ENCRYPTION_KEY) as Gmail.
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
# `common` = any work/school/personal MS account. Override to a
# specific tenant GUID for single-tenant production.
MICROSOFT_TENANT = os.getenv("MICROSOFT_TENANT", "common")
MICROSOFT_GRAPH_REDIRECT_URI = os.getenv(
    "MICROSOFT_GRAPH_REDIRECT_URI",
    "http://localhost:8000/api/v1/email/microsoft/callback",
)
# Public HTTPS URL Graph will POST change notifications to. Must be
# reachable from the internet (localhost won't work — Graph rejects
# subscription creation with a non-public URL). For dev, tunnel via
# ngrok and set this to the public ngrok URL. Leave empty to disable
# subscriptions; sync falls back to Step 4's 60-second poll.
MICROSOFT_GRAPH_WEBHOOK_URL = os.getenv(
    "MICROSOFT_GRAPH_WEBHOOK_URL", ""
)

# Developer Token — separate from OAuth, attached to Google Ads
# Manager (MCC) account. See Stage 4 of the manual checklist.
GOOGLE_ADS_DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
# Google Ads REST API version pin. New versions land roughly every
# two months and tend to deprecate the previous one within ~14 months;
# bumping is a separate small task (literal swap + a couple of
# response-shape adjustments). Override via env if a sunset forces it.
GOOGLE_ADS_API_VERSION = os.getenv("GOOGLE_ADS_API_VERSION", "v17")
# Where the frontend lives — the OAuth callback redirects here on
# completion (?status=google_connected). Uses FRONTEND_URL from above
# in callback construction; declared here as a documentation anchor.
# (No new env var needed.)

# Meta (Facebook + Instagram) Ads OAuth — Track 4 Step 4.
# Provision from a Meta app at developers.facebook.com; see
# tasks/ad-integrations/manual-meta-oauth-setup.md.
# Test users on the app dashboard bypass App Review for the
# `leads_retrieval` permission, so dev works today; production needs
# 1-2 weeks of Meta App Review.
META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_OAUTH_REDIRECT_URI = os.getenv(
    "META_OAUTH_REDIRECT_URI",
    "http://localhost:8000/api/v1/integrations/meta/callback",
)
# Random secret SHARED with the Meta app's Webhooks tab — Meta sends
# it back to us during the GET-time subscription verification handshake
# (Step 5). Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
# and paste the SAME value into both .env and the Meta app dashboard.
META_WEBHOOK_VERIFY_TOKEN = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "")
# Graph API version pin. Meta deprecates roughly every ~24 months;
# bumping is a literal swap + a couple of response-shape adjustments.
META_GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v19.0")

# Celery / Redis
CELERY_ENABLED = os.getenv("CELERY_ENABLED", "false").lower() == "true"
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB_BROKER = int(os.getenv("REDIS_DB_BROKER", "0"))
REDIS_DB_RESULT = int(os.getenv("REDIS_DB_RESULT", "1"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# Stripe (Track 4 Pricing & Billing, Step 11)
# `sk_test_...` / `pk_test_...` for dev, `sk_live_...` / `pk_live_...` for prod.
# `STRIPE_WEBHOOK_SECRET` (`whsec_...`) comes from the Stripe Dashboard
# after registering the FurnitureCRM webhook endpoint.
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
