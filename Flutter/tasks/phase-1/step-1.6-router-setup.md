# Step 1.6 — Router Setup (GoRouter + Guards)

> **Status:** COMPLETED

> **Phase 1: Project Setup & Core Infrastructure**
> Read `Flutter/docs/COMPONENT_REFERENCE.md` — "Routing — GoRouter" section.

**Prerequisites:** Step 1.5

---

**What to do:**
1. Create `lib/core/router/app_router.dart` — GoRouter configuration
2. Create `lib/core/guards/auth_guard.dart` — redirect logic (unauthenticated → login, authenticated → dashboard)
3. Set up ShellRoutes for auth layout and user layout (placeholder widgets for now)
4. Define all route paths (from `app_routes.dart` constants)

**Route structure:**
```
/login          → LoginScreen (placeholder)
/register       → RegisterScreen (placeholder)
/forgot-password → ForgotPasswordScreen (placeholder)
/reset-password  → ResetPasswordScreen (placeholder)
/two-factor     → TwoFactorScreen (placeholder)
/verify-email   → VerifyEmailScreen (placeholder)

ShellRoute (UserLayout):
  /user/dashboard      → DashboardScreen (placeholder)
  /user/profile        → ProfileScreen (placeholder)
  /user/security       → SecurityScreen (placeholder)
  /user/change-password → ChangePasswordScreen (placeholder)
  /user/login-history  → LoginHistoryScreen (placeholder)
  /user/support/tickets → TicketListScreen (placeholder)
  /user/support/compose → ComposeTicketScreen (placeholder)
  /user/support/view/:id → ViewTicketScreen (placeholder)
```

**Verify:**
- [ ] Router compiles with all routes
- [ ] Auth guard redirects unauthenticated users to /login
- [ ] Auth guard redirects authenticated users away from /login
- [ ] Placeholder screens render correctly

---

## Completion

This step is already completed. No action needed.


