# Step 1.9 — Frontend bootstrap (Angular)

**Goal:** Wire the Angular shell to the new backend — environment files, JWT HTTP interceptor adapted to the new endpoint shapes, global error handler, login flow updated to the new `POST /api/v1/auth/login`. Replace the Step 1.1 home stub with a real Tailwind-styled welcome component that calls the new `/users/me`. Tailwind is already installed (Step 1.1).
**Phase:** 1
**Depends on:** 1.6, 1.1
**Status:** Pending

## Scope
**In-scope:**
- New `app/src/environments/environment.ts` and `environment.development.ts` with `apiBaseUrl=http://localhost:8000/api/v1`.
- `app/src/app/features/user/core/auth/auth.service.ts` — wraps the new login endpoint, accepts `{email, password, org_slug}`, stores token + refresh.
- `app/src/app/features/user/core/auth/jwt.interceptor.ts` — attaches `Authorization: Bearer <token>` from token storage; on 401 attempts one refresh; on refresh failure → clear tokens + redirect to `/accounts/login`.
- `app/src/app/features/user/core/auth/auth.guard.ts` — wraps the existing `authGuard` if present, or replaces; redirects to `/accounts/login` if no token.
- `app/src/app/features/user/core/auth/token-storage.service.ts` — wraps localStorage for `access_token` + `refresh_token`.
- `app/src/app/features/user/core/error/global-error-handler.ts` — catches uncaught errors; logs them.
- `app/src/app/features/user/layout/welcome.component.ts/.html` — replaces the Step 1.1 home stub with a real Tailwind welcome that calls `/users/me` and displays the user's full name + role.
- Update `app/src/app/app.config.ts` to register the interceptor + error handler + provide HttpClient.
- Update `app/src/app/features/user/user.routes.ts` to swap the home-stub route for the new `WelcomeComponent`.
- Verify the existing PrimeNG/Material accounts pages still build and run unchanged.

**Out of scope:**
- Sidebar / header / module-driven menu — that's Step 1.10.
- Replacing/deleting the existing `app/src/app/core/services/auth.service.ts` (the legacy one) — kept until the legacy `/admin/...` flow is officially decommissioned (which we are not doing — it stays untouched per locked decision). The legacy service continues to power admin login.
- Tailwind installation/config — already done in Step 1.1.

## Files to touch
- `app/src/environments/environment.ts` (created)
- `app/src/environments/environment.development.ts` (created)
- `app/src/app/features/user/core/auth/auth.service.ts` (created)
- `app/src/app/features/user/core/auth/jwt.interceptor.ts` (created)
- `app/src/app/features/user/core/auth/auth.guard.ts` (created — or extends existing)
- `app/src/app/features/user/core/auth/token-storage.service.ts` (created)
- `app/src/app/features/user/core/error/global-error-handler.ts` (created)
- `app/src/app/features/user/layout/welcome.component.ts` (created)
- `app/src/app/features/user/layout/welcome.component.html` (created)
- `app/src/app/features/user/layout/home-stub.component.ts/.html` (deleted — replaced by Welcome)
- `app/src/app/features/user/user.routes.ts` (modified — swap route to WelcomeComponent)
- `app/src/app/app.config.ts` (modified — register interceptor + error handler)

## Plan
1. Create environment files; pin `apiBaseUrl`.
2. Token storage service: `setTokens(access, refresh)`, `clear()`, `getAccess()`, `getRefresh()`.
3. Auth service: `login(email, password, orgSlug)`, `refresh()`, `logout()`, `me()` — calls FurnitureCRM new endpoints.
4. JWT interceptor: header attach; on 401 try refresh once; on fail clear + navigate.
5. Auth guard: returns false + navigate to `/accounts/login` if no access token.
6. Global error handler: rxjs uncaught errors logged to `console.error`.
7. Welcome component: signal-based, calls `authService.me()` on init, displays `Welcome, {{ user.full_name }} ({{ user.role.name }})`. Uses Tailwind classes (already installed).
8. Update `user.routes.ts` to load `WelcomeComponent`. Delete `home-stub.component.*`.
9. Wire interceptor + error handler in `app.config.ts`.
10. Verify existing accounts (login/register/2FA) pages still render with PrimeNG/Material untouched.

## DB changes / migrations
None.

## Tests to add
- Skipped per project rule (`skipTests: true`); rely on manual smoke per checklist.

## Verification checklist
**Frontend:**
- run: `cd app && npx ng serve` → builds clean.
- visit: `http://localhost:4200/accounts/login` → existing PrimeNG/Material login page (visually unchanged).
- log in with seeded admin (FurnitureCRM admin role) using the new endpoint → redirected to `/user` → "Welcome, Admin User (Admin)" rendered with Tailwind classes.
- DevTools → Network: requests to `/api/v1/...` carry `Authorization: Bearer …`.
- DevTools → Application → localStorage: contains `access_token`, `refresh_token`.
- Refresh page → still logged in (token persists).
- Visual check: existing accounts pages unchanged from Step 1.1 baseline.
- Visual check: `/admin/dashboard` (legacy template) still renders if you hit it with the legacy admin login flow.

**Code review:**
- open `features/user/core/auth/jwt.interceptor.ts` — note refresh-then-retry on 401.
- open `features/user/layout/welcome.component.html` — note Tailwind classes only.

## Self-check (10 rules)
- [ ] Existing PrimeNG/Material auth pages untouched (option (a) honored).
- [ ] Legacy `features/admin/` folder untouched.
- [ ] No imports from `packs/` in `core/`.
- [ ] No TODOs / commented code.

## Stop & report
Use the master-prompt stop template; await "proceed" before Step 1.10.
