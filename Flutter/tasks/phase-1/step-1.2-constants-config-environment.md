# Step 1.2 — Constants, Config & Environment

> **Status:** COMPLETED

> **Phase 1: Project Setup & Core Infrastructure**
> Read `Flutter/docs/CODING_STANDARDS.md` for naming conventions.

**Prerequisites:** Step 1.1

---

**What to do:**
1. Create `lib/core/config/app_config.dart` — environment configuration (API base URL, app name)
2. Create `lib/core/constants/app_constants.dart` — app-wide constants
3. Create `lib/core/constants/messages.dart` — user-facing message strings
4. Create `lib/core/constants/app_routes.dart` — route name constants
5. Create `lib/core/constants/api_endpoints.dart` — API endpoint path constants

**Files:**

`app_config.dart`:
- `apiBaseUrl` — base URL for the FastAPI backend (configurable per environment)
- `appName` — application display name

`app_constants.dart`:
- Page sizes, timeout durations, OTP length, max file size, etc.

`messages.dart`:
- Success messages, error messages, validation messages (matching backend's `messages.py` pattern)

`app_routes.dart`:
- Route name constants (login, register, forgotPassword, userDashboard, etc.)

`api_endpoints.dart`:
- All API endpoint paths as constants (e.g., `static const login = '/auth/login'`)

**Verify:**
- [ ] All constants files compile without errors
- [ ] No hardcoded strings that should be constants

---

## Completion

This step is already completed. No action needed.


