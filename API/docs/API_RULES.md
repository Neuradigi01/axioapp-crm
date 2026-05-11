# API Development Rules & Conventions

> **Purpose:** Rules and conventions for API development. For full code templates, see `API_REFERENCE.md`.

---

## 1. Project Structure

```
Api/
├── main.py                  # FastAPI app initialization & global middleware
├── config.py                # Environment configuration (dotenv)
├── requirements.txt         # Production dependencies
├── alembic/                 # Alembic migration files
│   ├── alembic.ini
│   ├── env.py
│   └── versions/            # Migration scripts
├── docs/
│   ├── DATABASE_RULES.md    # ORM model rules
│   └── DATABASE_REFERENCE.md # ORM model templates
├── src/
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── __init__.py      # Base model & exports
│   │   ├── user.py          # tbl_user_login, tbl_user_info
│   │   ├── admin.py         # tbl_admin
│   │   ├── routes.py        # tbl_routes, tbl_admin_routes
│   │   └── ...
│   ├── routers/             # HTTP layer — thin, parse request, call service, return response
│   │   ├── __init__.py      # Main router aggregation
│   │   ├── auth/            # Login, register, forgot/change password, 2FA
│   │   ├── admin/           # Admin dashboard, sub-admin management
│   │   ├── user/            # User dashboard, profile
│   │   ├── websocket/       # WebSocket endpoints (thin: auth, parse, delegate)
│   │   └── ...
│   ├── services/            # Business/service logic + DB orchestration (receives db: AsyncSession)
│   │   ├── auth/            # Login, registration, password reset, resolver, login history
│   │   ├── admin/           # Admin profile, sub-admin, user management
│   │   ├── user/            # User profile service
│   │   ├── security/        # 2FA, action verification, verification
│   │   ├── content/         # News, notifications, popups
│   │   ├── ticket/          # Ticket & attachment services
│   │   ├── website/         # Contact us, newsletter
│   │   ├── dev/             # Route management (dev only)
│   │   ├── common_service.py    # Shared user/admin logic
│   │   ├── app_config_service.py
│   │   ├── location_service.py
│   │   └── utils_service.py
│   ├── ws_emitters/         # WebSocket broadcast layer (one function per event)
│   │   └── *_ws_emitter.py  # Domain-specific emitter files
│   ├── data_access/         # Reusable query functions (receives db: AsyncSession)
│   │   ├── user_da.py
│   │   ├── admin_da.py
│   │   ├── route_da.py
│   │   └── ...
│   ├── providers/           # Utility/infrastructure providers (email, SMS, OTP, error log)
│   │   ├── email_provider.py
│   │   ├── sms_provider.py
│   │   ├── otp_provider.py
│   │   └── ...
│   ├── schemas/             # Pydantic request/response models
│   │   ├── auth.py
│   │   └── ...
│   ├── core/
│   │   ├── db.py            # SQLAlchemy async engine, session & get_db dependency
│   │   ├── logger.py        # Logging configuration
│   │   └── security/        # JWT, password hashing, RBAC
│   │       ├── jwt.py
│   │       ├── password.py
│   │       ├── access_guard.py
│   │       └── role_checker.py
│   ├── constants/
│   │   ├── messages.py      # Response messages
│   │   ├── validators.py    # Field validators
│   │   ├── ws_events.py     # WebSocket event type constants
│   │   └── ws_channels.py   # WebSocket/Redis channel pattern constants
│   └── utilities/           # Helper functions
│       ├── aes_util.py
│       └── app_utils.py     # send_mail_async, send_sms_async, get_ip_info, etc.
└── data/                    # JSON configs, keys, etc.
    └── routes.json          # Route definitions for RBAC
```

---

## 2. Layer Responsibilities

### Router (HTTP layer)
- Parse request, extract data from `Request` (IP, user agent)
- Inject `db: AsyncSession = Depends(get_db)`
- Call service layer, return result
- **No business logic, no direct DB queries, no helper/utility functions**
- Routers must be thin — if you need a helper function (e.g., building a URL, formatting data), put it in the service layer or utilities, never in the router file

### Service Layer (`src/services/`)
- Organized into **subdirectories by domain**: `auth/`, `admin/`, `user/`, `security/`, `content/`, `ticket/`, `website/`, `dev/`
- Cross-cutting services remain at the root level: `common_service.py`, `app_config_service.py`, `location_service.py`, `utils_service.py`
- Feature-specific logic (authentication, user management, etc.)
- Orchestrates data access queries, providers, and application rules
- Receives `db: AsyncSession` from router — **never creates its own session**
- Calls `db.commit()` when the operation is complete

### Data Access Layer (`src/data_access/`)
- Reusable query functions — each receives `db: AsyncSession` as first param
- **No session management** — just build query, execute, return result
- **No commits, no flushes** (unless creating records where flush is needed for IDs)
- Eliminates duplicate queries across service modules

### Providers (`src/providers/`)
- Utility/infrastructure providers: email, SMS, OTP, error logging
- **Not feature-specific** — reusable across service modules
- Providers that need DB receive `db: AsyncSession` as first param
- Middleware/lifespan providers (error_log, route_provider) use `async_session()` directly

### Models (`src/models/`)
- SQLAlchemy ORM models — the data structure layer
- Use `Text` for all string columns (not `String(n)`)

### WebSocket Router (`src/routers/websocket/`)
- **Thin:** authenticate, accept connection, subscribe to channels, parse incoming messages, delegate to services
- Keeps pong/error responses inline — simple protocol messages
- **No business logic, no payload construction**

### WS Emitter Layer (`src/ws_emitters/`)
- **Analogous to the DA layer** — services never construct raw WS payloads, they call emitter functions
- One function per event type with **explicit typed parameters** — constructs payload dict internally
- Services call emitters; emitters call `manager.publish()` / `manager.send_personal()`
- Services do NOT import `manager`, `WsChannel`, or event constants for broadcasting

### WebSocket Layer Separation

| Layer | Knows about | Does NOT know about |
|-------|-------------|---------------------|
| WS Router | WS protocol, auth, message parsing | Channels, event names, payload structure |
| Service | Business rules, DB via DA, emitter calls | `manager`, channels, event names |
| WS Emitter | Event names, channels, `manager` | Business rules, DB |
| Data Access | SQL queries, ORM models | WebSocket, business rules |

---

## 3. File Organization

When creating a new feature module (e.g., "notifications"):
1. Create model file (if new tables): `src/models/notification.py`
2. Create data access file: `src/data_access/notification_da.py`
3. Create service file in the appropriate subdirectory: `src/services/content/notification_service.py`
4. Create router folder: `src/routers/notifications/`
5. Create schema file: `src/schemas/notification.py`
6. Register router in `src/routers/__init__.py`
7. Create Alembic migration: `alembic revision --autogenerate -m "add notifications table"`

---

## 4. Database / ORM Rules

1. **All database operations go through SQLAlchemy ORM** — no raw SQL unless absolutely necessary
2. **Use `db: AsyncSession` from `Depends(get_db)`** — one session per request, shared across all layers
3. **Business layer commits** — DA layer never commits
4. **Models define the schema** — tables, relationships, constraints
5. **Use Alembic** for all schema changes — never modify the database directly
6. **User IDs are case-insensitive** — always use `func.lower()` in queries and store lowercase

---

## 5. Schema Conventions

### Schema file naming: `src/schemas/feature_name.py` (lowercase snake_case)

### Common Validators (from `src/constants/validators.py`)

| Validator | Values |
|-----------|--------|
| `VALIDATORS.USER_TYPE` | `'Admin'`, `'User'` |
| `VALIDATORS.USER_TYPE_ALL` | `'All'`, `'Admin'`, `'User'` |
| `VALIDATORS.STATUS_ALL` | `'All'`, `'Active'`, `'Inactive'`, `'Blocked'` |
| `VALIDATORS.TWO_FACTOR_METHODS` | `'authenticator'`, `'email'`, `'sms'` |

---

## 6. Exception Handling

**DO NOT add try-catch blocks** in routes for general errors — the app has global exception handlers in `main.py`.

Add try-catch ONLY when:
1. Specific error recovery logic is needed
2. External API calls might fail (email, SMS)
3. Background task coordination is required

### Error Messages
Use predefined messages from `src/constants/messages.py`.

---

## 7. Authentication & Authorization

### Auth Flow
- **Login:** User submits credentials → service layer verifies password → checks 2FA → returns JWT token
- **Registration:** User submits details → validate uniqueness → create records → send welcome email
- **Forgot Password:** Email → generate reset token → send email → user resets
- **2FA:** Authenticator (TOTP), Email OTP, SMS OTP — configurable per user

### Route Protection
- **Router-level auth:** `router = APIRouter(dependencies=[Depends(get_current_user)])`
- **Route-level roles:** `dependencies=[Depends(RoleChecker(['Admin']))]`
- **Dynamic access:** `dependencies=[Depends(AccessGuard([route_id]))]`
- **Token payload:** `user_id`, `role`, `access_rights`, `is_super_admin` (for admins)
- **NEVER put internal DB IDs in the JWT** (`member_id`, `admin.id`, etc.) — these are internal DB row serials. All external interfaces use `user_id` (string). If `member_id` or `admin.id` is needed for a DB join/update, the service layer resolves it internally by fetching the record via `user_id` first.

---

## 8. Response Format

```python
# Success with data (list)
{'success': True, 'message': 'OK', 'data': [...], 'data_count': 100}

# Success with data (single)
{'success': True, 'message': 'OK', 'data': {...}}

# Success without data
{'success': True, 'message': 'Operation completed successfully!'}

# Failure
{'success': False, 'message': 'Error message'}
```

---

## 9. Import Template

```python
# Router imports
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.core.security.jwt import get_current_user
from src.core.security.role_checker import RoleChecker
from src.schemas.auth import LoginRequest
from src.services.auth import login_service
from src.utilities.app_utils import get_real_client_ip, get_ip_info
```

---

## 10. New Feature Checklist

### Planning
- [ ] Understand requirements completely
- [ ] Read `DATABASE_RULES.md` if new tables are needed
- [ ] Review existing models, DA, and service modules for patterns

### Database Layer
- [ ] Create/update model in `src/models/` (use `Text` for strings)
- [ ] Create data access functions in `src/data_access/` (receive `db: AsyncSession`)
- [ ] Generate Alembic migration

### Business Layer
- [ ] Create service module in appropriate `src/services/<domain>/` subdirectory (receive `db: AsyncSession`)
- [ ] Use DA functions for queries, providers for email/SMS/OTP

### API Layer
- [ ] Create schema: `src/schemas/feature_name.py`
- [ ] Create router: `src/routers/feature_name/`
- [ ] Router injects `db = Depends(get_db)`, calls service layer
- [ ] Register router in `src/routers/__init__.py`

### Security
- [ ] Add route protection (`get_current_user`, `RoleChecker`, `AccessGuard`)
- [ ] Validate all user inputs via Pydantic schemas

---

> For full code templates and examples, see `API_REFERENCE.md`.
