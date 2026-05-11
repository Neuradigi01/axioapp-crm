# API Agent Index

> **Purpose:** Entry point for AI agents working on the API. Contains essential rules and pointers to detailed docs.

---

## 1. Terminal Command Rules (Windows)

- Execute as FEW terminal commands as possible — combine with `&&`
- Always use `cmd /c "..."` wrapper: `cmd /c "cd /d D:\Projects\... && pip install && uvicorn main:app"`
- Use `cd /d` for changing drives
- Never run commands unnecessarily — think before executing
- Never run commands in PowerShell without CMD wrapper

## 2. Code Quality

- Every piece of code MUST be **production-ready** — no placeholders, no TODOs
- Never leave work unfinished — complete all related files (imports, exports, configs)
- DO NOT create unless explicitly asked: documentation files, test files, README updates, changelog entries, example files, unnecessary config files
- Focus ONLY on what was requested

## 3. Consistency

- **Study existing code patterns BEFORE writing new code**
- Match existing: naming conventions, file structure, import/export patterns, error handling, response formats, logging
- DO NOT: invent new patterns, use different naming, create new folder structures, refactor unrequested code, add unnecessary dependencies
- No dead code — remove unused imports, variables, functions

## 4. Project Architecture

- **Framework:** FastAPI with ORJSON serialization
- **Database:** PostgreSQL with SQLAlchemy ORM (async)
- **Migrations:** Alembic
- **Auth:** JWT Bearer tokens + Role-based access control (RBAC)
- **Async:** Full async support with asyncpg + SQLAlchemy async engine
- **Layers:** Routers (`src/routers/`) → Services (`src/services/<domain>/`) → Data Access (`src/data_access/`) + Providers (`src/providers/`) → Models (`src/models/`) → Schemas (`src/schemas/`) → Core (`src/core/`)
- **Router organization:** `src/routers/user/` for user-only, `src/routers/admin/` for admin-only, `src/routers/common/` for shared endpoints (e.g., 2FA, change-password). Common routers use `AccessGuard([user_route_id, admin_route_id])` and derive `user_type` from `token_payload["role"]` — never duplicate identical routers per user type. When user and admin endpoints share identical logic (same schema, same flow), they MUST go in `src/routers/common/` with a corresponding function in `src/services/common_service.py`.
- **Service layer:** Organized into **subdirectories by domain**: `auth/` (login, registration, password reset, resolver, login history), `admin/` (admin profile, sub-admin, user management), `user/` (user profile), `security/` (2FA, action verification, verification), `content/` (news, notifications, popups), `ticket/` (tickets, attachments), `website/` (contact us, newsletter), `dev/` (route management). Cross-cutting services remain at root level: `common_service.py`, `app_config_service.py`, `location_service.py`, `utils_service.py`. Import pattern: `from src.services.auth import login_service` (subdirectory) or `from src.services import common_service` (root level). Shared logic used by both user and admin goes in `src/services/common_service.py`. Extract common helpers (e.g., `_handle_2fa`) to avoid duplicating logic across `authenticate_user`/`authenticate_admin` style function pairs.
- **Data Access layer:** Reusable query functions. Each function receives `db: AsyncSession` — no session management, just query + return. Eliminates duplicate queries across service modules.
- **Providers:** Reusable utility/infrastructure providers (email, SMS, OTP, error logging) — not feature-specific. Providers contain only domain-specific logic (e.g., TOTP generation, email sending). Pure utility functions (masking, formatting) belong in `src/utilities/`.
- **Utilities:** Pure helper functions in `src/utilities/` — `formatting.py` (display purpose formatting, email/mobile masking), `app_utils.py` (IP extraction, email sending, template rendering), `aes_util.py` (encryption)
- **Constants:** `src/constants/messages.py` (all user-facing messages), `src/constants/route_ids.py` (semantic route ID constants — use `RouteIds.USER_DASHBOARD` instead of magic number `12`), `src/constants/validators.py`

### Layer Responsibilities (Strict)

**Routers** — Thin entry points ONLY. A router file must contain:
- Route decorator + endpoint function
- Request parsing (schema, Depends)
- A single call to a service function
- Nothing else. No helper functions, no business logic, no data access, no conditional branching beyond calling the service layer.

**Service layer** — ALL application logic lives here:
- Validation, authorization checks, conditional flows
- Orchestration of DA queries and providers
- Helper functions (prefixed with `_`) for shared logic within the same file
- Common service logic shared between user/admin goes in `src/services/common_service.py` (root level)
- Domain-specific services go in their subdirectory (e.g., `src/services/auth/login_service.py`, `src/services/security/two_factor_service.py`)

**Data Access layer** — Query functions only:
- Each function does one query and returns the result
- Receives `db: AsyncSession`, no session management
- Model-specific (user_da for UserLogin/UserInfo, admin_da for Admin)
- **Generic DA:** `src/data_access/generic_da.py` contains parameterized functions for operations identical across models (e.g., `update_password`, `update_two_factor`, `clear_two_factor`, `update_status`). Model-specific DA files delegate to generic_da to eliminate duplication. When adding a new model with the same update patterns, use generic_da instead of duplicating code.

### Anti-Duplication Rules

- **Schemas:** If user and admin use identical request/response shapes, define ONE schema in `src/schemas/common.py` — never duplicate (e.g., `ChangePasswordRequest`)
- **Routers:** If user and admin endpoints have identical logic (same schema, same flow), use a single common router — never create two identical routers with only route IDs differing. When two endpoints differ only in the service function called (e.g., `authenticate_user` vs `authenticate_admin`), keep them in the same router file — do NOT create a helper function in the router.
- **Business logic:** When two functions share >70% identical code, extract the common logic into a private helper function. Always check existing helpers before creating new ones (e.g., `resolve_record` reuses `_resolve_user`/`_resolve_admin`)
- **Data Access:** When user_da and admin_da have identical operations (e.g., update_password, clear_two_factor), delegate to `generic_da.py` — never duplicate query logic across DA files
- **Utilities:** Pure formatting/masking functions go in `src/utilities/` (not in providers). Before adding a new utility, check `src/utilities/formatting.py` and `src/utilities/app_utils.py`.
- **Route IDs:** Always use `RouteIds.SEMANTIC_NAME` from `src/constants/route_ids.py` in `AccessGuard()` calls — never hardcode magic numbers
- **Messages:** Use constants from `src/constants/messages.py` — never hardcode user-facing strings. Use context-appropriate constants: `USER_NOT_FOUND` for user contexts, `ADMIN_NOT_FOUND` for admin contexts, `RECORD_NOT_FOUND` for shared user/admin contexts (common_service, two_factor_service)

### Key Conventions
- ORM models use `tbl_` prefix for table names (e.g., `tbl_user_login`, `tbl_user_info`, `tbl_admin`)
- **All string columns use `Text` type** — never use `String(n)`. Validation happens at the schema/service layer, not the database layer
- API responses: `{'success': bool, 'message': str, 'data': ..., 'data_count': int}` — the `message` field is **always required**, even on success (use `messages.OK`)
- Authentication: `Depends(get_current_user)` + `Depends(RoleChecker([roles]))`
- JWT payload contains only: `user_id`, `role`, `access_rights`, `is_super_admin` (admins). **Never** include internal DB IDs (`member_id`, `admin.id`) — service layer resolves them internally via `user_id`.
- Database operations: Routers inject `db: AsyncSession = Depends(get_db)` and pass to service layer

### User/Admin Reference Rule (Strict)
- **Text `user_id` is ONLY stored in `tbl_user_login` and `tbl_admin`** as login identifiers
- **All other tables** referencing a user/admin MUST store the **integer primary key** (`member_id` as BigInteger or `created_by_id` as Integer FK)
- Polymorphic tables use `member_id` (BigInteger) + `user_type` discriminator — no FK since it references two tables
- Admin-only tables use proper FK to `tbl_admin.id`
- **Service layer** handles text↔integer resolution using `src/data_access/resolution_da.py`:
  - Write path: `resolve_member_id(db, text_user_id, user_type)` → integer
  - Read path: `batch_resolve_text_user_ids(db, [(member_id, user_type), ...])` → text user_ids
- **API responses NEVER expose integer IDs** — always resolve back to text `user_id` before returning

### Identifier Resolution Pattern
- Login and password-reset endpoints accept an `identifier` that can be **either a username or email**
- `_resolve_user(db, identifier)` — checks `user_id` first, then `email` if `@` present (loads `user_info` via relationship)
- `_resolve_admin(db, identifier)` — checks `admin_user_id` first, then `email` if `@` present
- `resolve_record(db, identifier, user_type)` — public wrapper, returns `(record, user_id, email, mobile)` tuple
- Always use these resolvers instead of direct DA calls when the input could be either username or email

### 2FA Available Methods Filtering
- `_get_available_2fa_methods(record, email, mobile)` determines which 2FA methods are usable:
  - `email` — only if `EMAIL_ENABLED=True` (config) AND user has email
  - `sms` — only if `SMS_ENABLED=True` (config) AND user has mobile
  - `authenticator` — only if user has `two_factor_secret` set
- Preferred method: `two_factor_method` if available, otherwise first available
- Login response includes `available_methods` list so the Angular app can offer "try another way"

### Login History
- Every successful login (user or admin) records an entry in `tbl_login_history`
- Captures: `user_id`, `user_type`, `ip_address`, `ip_info` (geo data from ipinfo.io), `user_agent`, `login_at`
- Always maintain this when modifying auth flows

### Table Naming
- `tbl_admin` — Admin credentials and settings
- `tbl_user_login` — User login credentials (user_id, password, 2FA key, 2FA enabled, is_active)
- `tbl_user_info` — User profile data (name, email, mobile, referral_id, member_id)
- `tbl_routes` — Route/permission definitions for dynamic access control
- `tbl_admin_routes` — Admin-to-route permission mapping (for sub-admins)

---

## 5. On-Demand Documentation

Read these files ONLY when needed for the current task. Do NOT read all files preemptively.

### API Development (Python/FastAPI)
When your task involves creating or modifying Python API code:
1. **Read first:** `API_RULES.md` — conventions, structure rules, and checklists
2. **Read when coding:** `API_REFERENCE.md` — full code templates and examples

### Database / ORM Development
When your task involves creating or modifying database models, migrations, or queries:
1. **Read first:** `DATABASE_RULES.md` — naming conventions, model rules, and checklists
2. **Read when coding:** `DATABASE_REFERENCE.md` — full ORM model templates and query examples

### Full Feature (API + Database)
1. Read both `API_RULES.md` and `DATABASE_RULES.md` first
2. Read the corresponding REFERENCE files only when actively writing code

---

## 6. Pre-Submission Checklist

- [ ] Used minimum necessary terminal commands with `cmd /c "..."` wrapper
- [ ] Code follows existing patterns exactly — no new patterns invented
- [ ] Work is 100% complete and production-ready
- [ ] No unnecessary files created (docs, tests, etc.)
- [ ] All imports/exports correct and integrated with existing code
- [ ] Error handling follows existing patterns
- [ ] Alembic migration created if models changed
- [ ] Router files contain ONLY route entry points — no helper functions or business logic
- [ ] No duplicate schemas — checked `src/schemas/common.py` for existing shared schemas
- [ ] No duplicate service logic — checked for existing helpers before creating new functions
- [ ] Shared user/admin logic uses common router + `common_service.py`, not two separate files
- [ ] Route IDs use `RouteIds.SEMANTIC_NAME` from `src/constants/route_ids.py` — no magic numbers
- [ ] User-facing messages use constants from `src/constants/messages.py` — no hardcoded strings
- [ ] Context-correct message constants: `USER_NOT_FOUND` for users, `ADMIN_NOT_FOUND` for admins, `RECORD_NOT_FOUND` for shared contexts
- [ ] All API responses include `message` field (use `messages.OK` for success)
- [ ] Duplicate DA operations (update_password, update_two_factor, etc.) delegate to `generic_da.py`
- [ ] Pure utility functions (masking, formatting) go in `src/utilities/`, not in providers

---

> **Golden Rule:** Write code as if a professional human developer wrote it — consistent, clean, complete, and indistinguishable from the existing codebase.
