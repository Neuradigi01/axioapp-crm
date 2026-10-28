# Flutter App — AI Agent Index

> **Read this file FIRST** before writing any Flutter code. It points to all other docs.

## Scope: USER PANEL ONLY

This Flutter app is the **user-side mobile application only**. There is NO admin panel in Flutter. All features are for the `User` role. The app connects to the same FastAPI backend as the Angular web app.

## Terminal Command Rules (Windows)

- Always wrap with `cmd /c "..."`
- Use `cd /d` for changing drives
- Combine commands with `&&`
- Minimize terminal commands — combine where possible

## Golden Rules

1. **Reuse before create** — check existing widgets, services, utilities before writing new ones
2. **Production-ready only** — no placeholders, no TODOs, complete all related files
3. **Match existing patterns** — study the codebase before writing, follow what exists
4. **No dead code** — remove unused imports, variables, functions
5. **No inline magic** — use constants, theme tokens, route helpers
6. **Strict typing** — no `dynamic` unless absolutely necessary, no implicit casts
7. **Immutable state** — use `@immutable` on widgets, prefer `final` fields
8. **Composition over inheritance** — prefer small, composable widgets

## Project Architecture (Quick Reference)

```
Flutter/
├── docs/                          # Documentation (you are here)
│   ├── AGENT_INDEX.md             # This file — start here
│   ├── CODING_STANDARDS.md        # Dart/Flutter coding standards
│   ├── COMPONENT_REFERENCE.md     # Widget patterns, routing, HTTP, state
│   └── THEMING_REFERENCE.md       # Theme system, tokens, dark/light mode
├── tasks/                         # Step-by-step implementation tasks
│   └── README.md                  # Task index with phase overview
├── lib/
│   ├── main.dart                  # App entry point
│   ├── app.dart                   # MaterialApp.router setup
│   ├── core/                      # Core infrastructure
│   │   ├── config/                # Environment config, API base URL
│   │   ├── constants/             # App constants, messages, route IDs
│   │   ├── router/                # GoRouter setup, route definitions
│   │   ├── services/              # Core services (auth, theme, storage)
│   │   ├── network/               # HTTP client, interceptors, API helper
│   │   └── guards/                # Route guards (auth, role)
│   ├── models/                    # Data models (freezed/json_serializable)
│   ├── schemas/                   # Request/response DTOs
│   ├── services/                  # Feature API services
│   │   ├── auth_api_service.dart
│   │   ├── user_api_service.dart
│   │   ├── ticket_api_service.dart
│   │   └── ...
│   ├── providers/                 # Riverpod providers (state management)
│   ├── features/                  # Feature modules (screens + widgets)
│   │   ├── auth/                  # Login, Register, Forgot Password, 2FA
│   │   │   ├── screens/
│   │   │   └── widgets/
│   │   ├── user/                  # User panel screens
│   │   │   ├── screens/
│   │   │   └── widgets/
│   │   └── shared/                # Shared feature widgets (support, 2FA settings)
│   │       ├── screens/
│   │       └── widgets/
│   ├── shared/                    # Shared UI components
│   │   ├── widgets/               # Reusable widgets (buttons, cards, dialogs)
│   │   ├── layouts/               # Layout shells (auth, user)
│   │   └── extensions/            # Dart extensions
│   └── utils/                     # Pure utility functions
├── assets/                        # Images, fonts, etc.
├── test/                          # Tests (optional, as needed)
├── pubspec.yaml                   # Dependencies
└── analysis_options.yaml          # Lint rules
```

## Layer Organization

```
Screens (UI) → Providers (State) → API Services (Network) → Models/Schemas
```

| Layer | Responsibility | Location |
|-------|---------------|----------|
| **Screens** | UI rendering, user interaction, form handling | `lib/features/*/screens/` |
| **Widgets** | Reusable UI pieces within a feature | `lib/features/*/widgets/` |
| **Shared Widgets** | Cross-feature reusable UI | `lib/shared/widgets/` |
| **Providers** | State management, business logic | `lib/providers/` |
| **API Services** | HTTP calls, request/response mapping | `lib/services/` |
| **Models** | Data classes for domain entities | `lib/models/` |
| **Schemas** | Request/response DTOs | `lib/schemas/` |
| **Core Services** | Auth, theme, storage, navigation | `lib/core/services/` |
| **Network** | HTTP client, interceptors | `lib/core/network/` |
| **Utils** | Pure helper functions | `lib/utils/` |

## Naming Conventions

| Entity | Convention | Example |
|--------|-----------|---------|
| Files/folders | snake_case | `login_screen.dart`, `auth_api_service.dart` |
| Classes | PascalCase | `LoginScreen`, `AuthApiService` |
| Variables/functions | camelCase | `isLoading`, `fetchProfile()` |
| Constants | camelCase (top-level) or UPPER_SNAKE_CASE (in class) | `apiBaseUrl`, `AppConstants.APP_NAME` |
| Providers | camelCase + `Provider` suffix | `authProvider`, `userProfileProvider` |
| Enums | PascalCase (type), camelCase (values) | `UserRole.admin`, `TicketStatus.open` |
| Routes | camelCase route names | `AppRoutes.login`, `AppRoutes.userDashboard` |
| Private members | `_` prefix | `_isLoading`, `_fetchData()` |
| Models | PascalCase, no prefix | `UserProfile`, `LoginResponse` |
| Schemas (DTOs) | PascalCase + `Request`/`Response` | `LoginRequest`, `ProfileUpdateRequest` |

## Anti-Duplication Rules

| What | Rule |
|------|------|
| **API calls** | All HTTP calls go through `ApiHelper` → feature API services. Never use `http`/`dio` directly in screens |
| **Constants** | Centralized in `lib/core/constants/`. No hardcoded strings, URLs, or magic numbers |
| **Messages** | User-facing strings in `lib/core/constants/messages.dart` |
| **Routes** | Dynamic route lookup via `RoutesHelper`. Never hardcode paths |
| **Models** | One model per entity. Shared models in `lib/models/` |
| **Schemas** | Request/response DTOs in `lib/schemas/`. If user/admin share identical structure, define ONCE |
| **Theme values** | All colors, spacing, typography via theme tokens. No hardcoded values |
| **Widgets** | If a widget is used in 2+ features, move to `lib/shared/widgets/` |
| **Validation** | Reusable validators in `lib/utils/validators.dart` |

## Key Technical Decisions

| Area | Choice | Reason |
|------|--------|--------|
| **State Management** | Riverpod | Compile-safe, testable, no context dependency |
| **Routing** | GoRouter | Declarative, deep linking, guards, shell routes |
| **HTTP Client** | Dio | Interceptors, retry, multipart uploads |
| **Models** | freezed + json_serializable | Immutable, union types, JSON serialization |
| **Local Storage** | flutter_secure_storage + shared_preferences | Secure token storage + general preferences |
| **Forms** | Flutter built-in (TextFormField + Form) | Sufficient for our needs |
| **Theming** | Material 3 with custom tokens | Consistent with backend admin Angular app |
| **Push Notifications** | firebase_messaging | FCM integration matching existing backend |
| **Image Handling** | cached_network_image | Efficient image loading with caching |
| **File Picker** | file_picker | Cross-platform file selection |

## Critical Architectural Patterns

### 1. Action Verification — Reusable 2FA (Dio Interceptor)
The **most important pattern** in this app. A Dio interceptor catches `403 + error_code: "2FA_REQUIRED"` from ANY API call, shows a modal 2FA dialog, gets an action token, and **retries the original request** with `X-Action-Token` header. No screen needs to implement 2FA — it's fully automatic and API-controlled.

See `COMPONENT_REFERENCE.md` → "Action Verification" section for full implementation details.

### 2. CAPTCHA — 3 Types, API-Controlled
Backend controls CAPTCHA (enable/disable/type). Flutter must support all 3:
- **Image** — server-generated base64 image + text input
- **reCAPTCHA v2** — Google checkbox widget
- **reCAPTCHA v3** — invisible, score-based

A single `CaptchaWidget` renders the correct type based on `GET /auth/captcha` response. Used in login and registration.

See `COMPONENT_REFERENCE.md` → "CAPTCHA System" section for full implementation details.

### 3. Dynamic Routes — Menu from Backend
Sidebar menu items are loaded from `/api/routes/config` on app startup. Only routes the user has access to (based on `accessRights` in JWT) are shown. Adding a new route to the backend automatically shows it in the app menu.

## Backend Integration

This Flutter app connects to the **same FastAPI backend** as the Angular app. All API endpoints, auth flow, and data structures are identical.

- **Base URL:** Configured per environment in `lib/core/config/`
- **Auth:** JWT Bearer tokens (same as Angular)
- **Response format:** `{'success': bool, 'message': str, 'data': ..., 'data_count': int}`
- **Routes:** Loaded dynamically from `/api/routes/config` on app startup
- **2FA:** Authenticator, Email OTP, SMS OTP (same flow)
- **CAPTCHA:** 3 types (image, reCAPTCHA v2, reCAPTCHA v3) — API-controlled
- **Action Verification:** Automatic 2FA via Dio interceptor — API-controlled

## On-Demand Documentation

Read docs ONLY when needed for current task:

| When | Read |
|------|------|
| Writing any Dart/Flutter code | `CODING_STANDARDS.md` |
| Building widgets, screens, routing, HTTP | `COMPONENT_REFERENCE.md` |
| Working on themes, colors, styling | `THEMING_REFERENCE.md` |
| Starting a new task | `tasks/README.md` → specific task file |

## Pre-Submission Checklist

- [ ] Code follows existing patterns exactly
- [ ] All code is production-ready — no placeholders
- [ ] No `dynamic` types — strict typing everywhere
- [ ] All HTTP calls go through API services (not direct Dio/http)
- [ ] Constants used for strings, messages, route IDs
- [ ] Theme tokens used for all colors/spacing (no hardcoded values)
- [ ] Routes use `RoutesHelper` — no hardcoded paths
- [ ] Widgets are `const` where possible
- [ ] No unused imports or dead code
- [ ] State management via Riverpod providers
- [ ] Models are immutable (freezed)
- [ ] Form validation uses shared validators
- [ ] Error handling follows existing patterns
- [ ] Loading states properly managed
- [ ] All related files updated (imports, exports, providers)
