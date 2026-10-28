# App Agent Index

> **Purpose:** Entry point for AI agents working on the Angular App. Contains essential rules and pointers to detailed docs.

---

## 1. Terminal Command Rules (Windows)

- Execute as FEW terminal commands as possible — combine with `&&`
- Always use `cmd /c "..."` wrapper: `cmd /c "cd /d D:\Projects\... && npm run build"`
- Use `cd /d` for changing drives
- Never run commands unnecessarily — think before executing

## 2. Golden Rules

- **Reuse before create.** If an existing file fits the purpose, modify it; do not create duplicates
- **Suggest reusability improvements.** If similar functionality exists but isn't reusable, suggest making it reusable first and wait for approval
- **Small, safe diffs.** Keep changes <= 200 LOC per ticket whenever possible
- **No stylistic drift.** Follow naming, structure, and patterns already used in the repo
- **No inline templates or styles.** Components must have separate `.html` and `.scss`
- **OnPush by default.** New/edited components must use `ChangeDetectionStrategy.OnPush`
- **Typed everything.** Strict TypeScript; no `any` unless explicitly justified
- **No new dependencies** without explicit note and minimal rationale
- **Accessibility** and **contrast** must be maintained (WCAG AA)
- Do NOT reorganize modules, rename paths, or alter tsconfig/eslint/prettier unless the ticket demands it

## 3. Code Quality

- Every piece of code MUST be **production-ready** — no placeholders, no TODOs
- Never leave work unfinished — complete all related files (imports, exports, configs)
- DO NOT create unless explicitly asked: documentation files, test files, README updates, changelog entries, example files, unnecessary config files
- Focus ONLY on what was requested

## 4. Project Architecture (Quick Ref)

- **Framework:** Angular (standalone components + feature-based routing, zoneless change detection)
- **Language:** TypeScript (strict, typed APIs)
- **Styles:** SCSS with theme files under `src/styles/`
- **UI Libraries:** Angular Material + PrimeNG
- **Patterns:** Feature-first folder structure, lazy loading, route guards, interceptors, signals
- **Routing:** Dynamic paths from DB via `getRoute()` — routes MUST be loaded from API on app init (no fallback). NEVER hardcode paths or URLs. Full routing rules and patterns in `COMPONENT_REFERENCE.md` §6

### Key Paths

| Area | Path |
|------|------|
| Features | `src/app/features/<feature>/` |
| Shared components | `src/app/shared/components/` |
| Shared directives | `src/app/shared/directives/` |
| Core services | `src/app/core/services/` |
| API services | `src/app/services/*-api.service.ts` |
| Guards/Interceptors | `src/app/core/guards/`, `src/app/core/interceptors/` |
| Constants | `src/app/core/constants/app.constants.ts` (all app constants), `messages.constants.ts` (UI messages), `ws-events.constants.ts` (WebSocket event types) |
| Schemas/DTOs | `src/app/schemas/` |
| Themes & tokens | `src/styles/tokens.scss`, `dark.scss`, `light.scss` |
| SCSS mixins | `src/styles/_auth-card.scss` (auth page shared styles) |
| Central config | `src/app/app.settings.ts` |
| HTTP helper | `src/app/core/services/http-helper.service.ts` (Promise-based via `firstValueFrom`, sets Content-Type only — auth token injected by `authInterceptor`) |

### Naming Conventions (Quick Ref)

| Symbol | Convention | Example |
|--------|-----------|---------|
| Files & folders | kebab-case | `user-profile.component.ts` |
| Classes, Enums | PascalCase | `TitleService`, `UserRole` |
| Interfaces | PascalCase with `I` prefix | `IUserProfile` |
| Functions, variables | camelCase | `fetchUserProfile` |
| Constants | UPPER_SNAKE_CASE | `DEFAULT_PAGE_SIZE` |
| Observables | suffix `$` | `user$`, `isLoading$` |
| CSS variables | `--kebab-case` | `--primary-color` |
| Route paths | kebab-case | `user-profile` |

### Angular Suffixes

`.component.ts`, `.service.ts`, `.guard.ts`, `.interceptor.ts`, `.routes.ts`, `.pipe.ts`, `.directive.ts`

## 5. Anti-Duplication Rules

These rules are **mandatory** for all new code. Violating them will require a rework.

### API Services (not HttpHelperService directly)
- Components MUST NOT call `HttpHelperService` directly for API calls
- Create or use an **API service** in `src/app/services/*-api.service.ts` (e.g., `AuthApiService`, `UserApiService`, `TwoFactorApiService`)
- API services wrap `HttpHelperService` and define all API URLs in one place — API services are NOT core services; they live in `src/app/services/`, separate from `src/app/core/services/`
- Components inject the API service, not `HttpHelperService`
- If an API endpoint is called from multiple places, it MUST be defined once in an API service

### Shared Constants
- All constants go in `src/app/core/constants/app.constants.ts` — roles (`ROLE_USER`, `ROLE_ADMIN`), theme values (`THEME_LIGHT`, `THEME_DARK`), storage keys (`STORAGE_KEY_TOKEN`, `STORAGE_KEY_THEME`), snackbar defaults (`SNACKBAR_DURATION`, `SNACKBAR_ACTION`), 2FA constants (`TFA_METHOD_LABELS`, `TFA_METHOD_ICONS`, `OTP_EXPIRY_SECONDS`, `RESEND_COOLDOWN_SECONDS`), badge map (`BADGE_MAP`)
- Reusable UI messages go in `src/app/core/constants/messages.constants.ts` — error messages (`MSG_ERROR_GENERIC`), success messages (`MSG_PROFILE_UPDATED`), 2FA messages (`MSG_2FA_ENABLED`), etc.
- Never duplicate constant maps across components — import from `core/constants/`
- Never hardcode role strings (`'User'`, `'Admin'`), theme strings, or localStorage keys — use constants

### Shared Interfaces/Types
- All interfaces and types go in `src/app/schemas/` files:
  - `common.ts` — shared types used across the app: `UserType`, `TwoFactorMethod`, `Theme`, `IApiResponse`, `ITokenPayload`, `IUserDetails`, `ICountdownTimer`, `IBadgeConfig`
  - `auth.ts` — auth-specific: `ILoginData`, `I2faRequiredData`, `ITryAnotherWayData`
  - `user.ts` — user-specific: `IUserProfile`, `IUserDashboardData`, `I2faStatus`, `ISetupAuthenticatorData`, `TfaView`
  - `shared.ts` — UI-specific: `IDashboardTile`, `IConfirmDialogData`, `IPageEvent`
  - `route.ts` — routing: `IRoute`, `INavMenuItem`
- **Never define interfaces inline in component or service files** — always import from `schemas/`
- When an API service handles typing via generics, components do not need to re-import the same interface

### WebSocket Event Constants
- **Never use raw event type strings** (`'message'`, `'typing'`, etc.) — use constants from `src/app/core/constants/ws-events.constants.ts`
- WebSocket service (`src/app/core/services/websocket.service.ts`) handles connection lifecycle — features use the shared service, never create their own WebSocket connections
- Event handler services (e.g., `*-event-handler.service.ts`) subscribe to WS events and delegate to feature logic — keep WS parsing separate from business logic

### Naming Consistency
- Loading state signals: always use `isLoading` (never `isProcessing` or other variants). Exception: `isSaving` is acceptable when a component has both a load state and a save state.
- Snackbar calls: always use `SNACKBAR_ACTION` and `SNACKBAR_DURATION` constants — never hardcode `'Close'` or `4000`
- API service URLs: always use leading slash (e.g., `'/user/profile'`, not `'user/profile'`)

### Shared SCSS
- Auth page card styles use the `_auth-card.scss` mixin (`@use 'styles/auth-card' as auth;`)
- Never duplicate card/header/form/actions/link styles across auth pages
- When multiple components share identical SCSS blocks, extract into a mixin in `src/styles/`

### Shared Directives & Utilities
- Use `PasswordToggleDirective` (`@shared/directives/password-toggle.directive.ts`) for password visibility toggles — never implement show/hide signals and toggle methods in components. Usage: `appPasswordToggle #pwToggle="passwordToggle"` on `mat-form-field`, then `pwToggle.type()`, `pwToggle.icon()`, `pwToggle.toggle()`, `pwToggle.ariaLabel()` in template
- Use `createCountdownTimer()` (`@core/services/countdown.service.ts`) for countdown/timer logic — never implement `setInterval` timers manually. Returns `{ remaining, start, stop, destroy }`
- Use `ValidationMessageComponent` (`@shared/components/validation-message/validation-message.component.ts`) for form field validation errors — **always wrap inside `<mat-error>`**, never place directly in `<mat-form-field>`. Pattern: `<mat-error><app-validation-message [control]="form.controls['field']" label="Field Label" /></mat-error>`

### Before Writing Any Code
1. Check if a similar API service method already exists in `src/app/services/`
2. Check if the interface/type already exists in `src/app/schemas/`
3. Check if the constant already exists in `src/app/core/constants/`
4. Check if a shared directive or utility already handles this pattern

### Layout Pattern: Admin Mirrors User
- The **admin layout** follows the exact same pattern as the **user layout** — sidenav, toolbar, user menu dropdown, dynamic menu building from access rights
- When implementing or modifying admin layout, **reference the user layout implementation** (`features/user/`) as the canonical pattern
- Both layouts share: `RoutesHelperService.getSideNavMenusFromAccessRights()` for menu building, toolbar with theme toggle + user dropdown (profile, password, security, logout), collapsible sidenav
- Differences: admin has role badge in toolbar, admin routes have additional sub-features (sub-admin, member management)

## 6. Reusability Detection

When implementing new functionality, AI agents MUST:

1. **Scan for similar existing code** before creating anything new
2. **Suggest reusability refactoring** if 80%+ similar functionality exists, following this format:

```
REUSABILITY SUGGESTION DETECTED

Similar functionality found:
- Existing: [path]
- Requested: [what was asked]

Suggested approach:
A) Refactor existing to be reusable, then use it
B) Create new duplicate (not recommended)

Awaiting approval before proceeding.
```

3. **Wait for explicit approval** before proceeding
4. Trigger conditions: same component type, same service methods, same utility functions, same validation patterns, same UI patterns

## 7. On-Demand Documentation

Read these files ONLY when needed for the current task. Do NOT read all files preemptively.

### Writing New Components, Services, or General Code
When your task involves creating or modifying Angular code:
1. **Read first:** `CODING_STANDARDS.md` — git workflow, testing, PWA, versioning, code review
2. **Read when doing CSS/theming:** `THEMING_REFERENCE.md` — 3-step token workflow, theme files, forbidden patterns
3. **Read when creating components:** `COMPONENT_REFERENCE.md` — Angular component contract, patterns, page layout system architecture

> **Note:** `COMPONENT_REFERENCE.md` includes the Page Layout System architecture (section 13). All new features MUST follow these patterns.

## 8. Pre-Submission Checklist

- [ ] Used minimum necessary terminal commands with `cmd /c "..."` wrapper
- [ ] Code follows existing patterns exactly — no new patterns invented
- [ ] Work is 100% complete and production-ready
- [ ] No unnecessary files created (docs, tests, etc.)
- [ ] All imports/exports correct and integrated with existing code
- [ ] OnPush change detection on all new/modified components
- [ ] No `any` types without justification
- [ ] No hardcoded colors — all via `var(--token-name)`
- [ ] No `::ng-deep` usage
- [ ] Separate `.html` and `.scss` files for all components
- [ ] Route files use `getRoute('control_id').path` — no hardcoded path strings or URLs (see §6 in COMPONENT_REFERENCE.md)
- [ ] API calls go through API services (`src/app/services/`), not `HttpHelperService` directly
- [ ] No inline interfaces — all types defined in `src/app/schemas/` (check `common.ts` first)
- [ ] No inline constants — shared constants go in `src/app/core/constants/app.constants.ts`
- [ ] No hardcoded error/success messages — use `src/app/core/constants/messages.constants.ts`
- [ ] No hardcoded role strings (`'User'`, `'Admin'`) — use `ROLE_USER`, `ROLE_ADMIN` from constants
- [ ] Loading signals named `isLoading` (not `isProcessing` or variants)
- [ ] No manual password toggle logic — use `PasswordToggleDirective`
- [ ] No manual `setInterval` timers — use `createCountdownTimer()`
- [ ] No duplicated SCSS — shared styles use mixins from `src/styles/`

---

> **Golden Rule:** Write code as if a professional human developer wrote it — consistent, clean, complete, and indistinguishable from the existing codebase.
