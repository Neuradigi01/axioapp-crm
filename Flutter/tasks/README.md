# Flutter App — Implementation Tasks

## Execution Rules

1. **Implement ONE step file per session** — complete the step, then STOP
2. The AI should read **only** the current step file + referenced docs
3. After each step, the user will verify all code and test the running app before proceeding to the next step
4. Each step is self-contained — it lists prerequisites, what to do, and how to verify
5. Every step must leave the app in a buildable, runnable state
6. Follow coding standards from `Flutter/docs/` — read AGENT_INDEX.md before writing any code
7. **After completing a step**, change its status from `PENDING` to `COMPLETED` at the top of the step file
8. **Before starting work**, check the status lines in step files to know what's already done — no need to scan the codebase

## How to Use

Tell the AI: **"Do step X.Y"** and it will read `Flutter/tasks/phase-X/step-X.Y-*.md` and execute it.

## Phase Overview

| Phase | Description | Steps |
|-------|-------------|-------|
| 1 | Project Setup & Core Infrastructure | 7 |
| 2 | Shared Widgets, CAPTCHA, Action Verify, Layouts | 9 |
| 3 | Auth: Login, 2FA, Email Verification | 6 |
| 4 | Auth: Registration & Password Reset | 5 |
| 5 | User Dashboard & Profile | 3 |
| 6 | Security, Password & Login History | 5 |
| 7 | Support Ticket System | 4 |
| 8 | Notifications, Popups & Final Polish | 7 |

**Total: 8 phases, 46 steps**

---

## All Steps (in order)

### Phase 1 — Project Setup & Core Infrastructure (`phase-1/`)
| Step | File | Description |
|------|------|-------------|
| 1.1 | `phase-1/step-1.1-create-project-folder-structure.md` | Create Flutter project, folder structure, dependencies |
| 1.2 | `phase-1/step-1.2-constants-config-environment.md` | Constants, config, API endpoints, route names |
| 1.3 | `phase-1/step-1.3-theme-system.md` | Light + Dark theme (ColorScheme, ThemeData, ThemeService) |
| 1.4 | `phase-1/step-1.4-network-layer.md` | Dio, ApiHelper, Auth interceptor, Action Verify interceptor |
| 1.5 | `phase-1/step-1.5-auth-service.md` | Token storage, AuthState, AuthNotifier |
| 1.6 | `phase-1/step-1.6-router-setup.md` | GoRouter, route guards, ShellRoutes, placeholders |
| 1.7 | `phase-1/step-1.7-app-entry-point.md` | main.dart, App widget, wire everything, first run |

### Phase 2 — Shared Widgets & Layouts (`phase-2/`)
| Step | File | Description |
|------|------|-------------|
| 2.1 | `phase-2/step-2.1-core-shared-widgets.md` | AppButton, AppTextField, PasswordField, AppCard |
| 2.2 | `phase-2/step-2.2-feedback-widgets.md` | Snackbar, ConfirmDialog, Loading, Empty, Error widgets |
| 2.3 | `phase-2/step-2.3-form-widgets.md` | Validators, OTP input (6-digit), Country/State picker |
| 2.4 | `phase-2/step-2.4-status-badge-pagination.md` | Status badge, Pagination controls |
| 2.5 | `phase-2/step-2.5-captcha-widget.md` | CAPTCHA widget (image, reCAPTCHA v2, reCAPTCHA v3) |
| 2.6 | `phase-2/step-2.6-action-verify-dialog.md` | Reusable 2FA dialog + service + interceptor wiring |
| 2.7 | `phase-2/step-2.7-file-upload-attachment.md` | File upload picker, Attachment list with download |
| 2.8 | `phase-2/step-2.8-auth-layout.md` | Auth layout shell (centered, scrollable, theme toggle) |
| 2.9 | `phase-2/step-2.9-user-layout.md` | User layout shell (Drawer, AppBar, profile menu, theme) |

### Phase 3 — Auth: Login, 2FA & Email Verification (`phase-3/`)
| Step | File | Description |
|------|------|-------------|
| 3.1 | `phase-3/step-3.1-auth-api-service-schemas.md` | Auth API service, freezed schemas, AppConfig |
| 3.2 | `phase-3/step-3.2-login-screen-ui.md` | Login form UI with CAPTCHA |
| 3.3 | `phase-3/step-3.3-login-functionality.md` | Login API integration, all response handling |
| 3.4 | `phase-3/step-3.4-two-factor-screen.md` | 2FA screen (OTP, method switching, countdown) |
| 3.5 | `phase-3/step-3.5-email-verification-notice.md` | Email verification notice page |
| 3.6 | `phase-3/step-3.6-email-verification.md` | Token-based email verification page |

### Phase 4 — Auth: Registration & Password Reset (`phase-4/`)
| Step | File | Description |
|------|------|-------------|
| 4.1 | `phase-4/step-4.1-location-api-models.md` | Location API, Country/State models |
| 4.2 | `phase-4/step-4.2-register-screen-ui.md` | Register form UI with CAPTCHA |
| 4.3 | `phase-4/step-4.3-register-functionality.md` | Register API + OTP pre-verification flow |
| 4.4 | `phase-4/step-4.4-forgot-password.md` | Forgot password screen |
| 4.5 | `phase-4/step-4.5-reset-password.md` | Reset password screen (token-based) |

### Phase 5 — User Dashboard & Profile (`phase-5/`)
| Step | File | Description |
|------|------|-------------|
| 5.1 | `phase-5/step-5.1-user-api-models.md` | User API service, Profile/Dashboard models |
| 5.2 | `phase-5/step-5.2-dashboard-screen.md` | Dashboard with tiles, greeting, responsive grid |
| 5.3 | `phase-5/step-5.3-profile-screen.md` | Profile view/edit with image upload/remove |

### Phase 6 — Security, Password & Login History (`phase-6/`)
| Step | File | Description |
|------|------|-------------|
| 6.1 | `phase-6/step-6.1-tfa-api-models.md` | 2FA API service, TfaStatus model |
| 6.2 | `phase-6/step-6.2-tfa-settings-widget.md` | 2FA settings (setup, enable, disable, change) |
| 6.3 | `phase-6/step-6.3-login-history.md` | Login history API, model, table widget |
| 6.4 | `phase-6/step-6.4-change-password.md` | Change password form + screen |
| 6.5 | `phase-6/step-6.5-security-login-history-screens.md` | Security page + standalone login history page |

### Phase 7 — Support Ticket System (`phase-7/`)
| Step | File | Description |
|------|------|-------------|
| 7.1 | `phase-7/step-7.1-ticket-api-models.md` | Ticket API, models (Ticket, Thread, Attachment) |
| 7.2 | `phase-7/step-7.2-ticket-list-screen.md` | Ticket list with search, filters, pagination |
| 7.3 | `phase-7/step-7.3-compose-ticket.md` | Compose ticket with file attachments |
| 7.4 | `phase-7/step-7.4-view-ticket.md` | View ticket thread + reply with attachments |

### Phase 8 — Notifications, Popups & Final Polish (`phase-8/`)
| Step | File | Description |
|------|------|-------------|
| 8.1 | `phase-8/step-8.1-app-initialization.md` | Dynamic routes from API, app config, auto-login |
| 8.2 | `phase-8/step-8.2-push-notifications.md` | Firebase FCM setup, device token registration |
| 8.3 | `phase-8/step-8.3-notification-bell.md` | Notification bell with unread count + list |
| 8.4 | `phase-8/step-8.4-popup-display.md` | Popup modal on dashboard load |
| 8.5 | `phase-8/step-8.5-news-feed.md` | News feed widget on dashboard |
| 8.6 | `phase-8/step-8.6-logout-session.md` | Logout flow, 401 handling, session management |
| 8.7 | `phase-8/step-8.7-final-polish.md` | QA checklist, lint, build, theme review |

---

## Feature Coverage

After all steps, the Flutter app will have full feature parity with the Angular user panel:

**Authentication:**
- Login with credentials + CAPTCHA (3 types: image, reCAPTCHA v2, reCAPTCHA v3)
- Two-factor authentication (Authenticator, Email OTP, SMS OTP)
- Registration with CAPTCHA + pre-verification OTPs
- Forgot password → Reset password
- Email verification

**User Panel:**
- Dashboard with metric tiles and news feed
- Profile view & edit with image upload
- Change password
- Security settings (2FA enable/disable/change)
- Login history with session management

**Support:**
- Ticket list with search, filter, pagination
- Compose ticket with file attachments
- View ticket thread with reply capability

**Infrastructure:**
- Light/Dark theme with persistence
- Dynamic route loading from backend (menus auto-generated from access rights)
- Push notifications (FCM)
- Popup announcements
- JWT auth with auto-refresh/logout
- **Reusable 2FA via Dio interceptor** — automatic, API-controlled, no per-page implementation
- **CAPTCHA** — 3 types, API-controlled (enable/disable/change type from backend)
- Responsive layout (mobile/tablet/desktop)

## Status Tracking

- [x] Phase 1 — Project Setup & Core Infrastructure (7 steps) — COMPLETED
- [x] Phase 2 — Shared Widgets, CAPTCHA, Action Verify, Layouts (9 steps) — COMPLETED
- [x] Phase 3 — Auth: Login, 2FA, Email Verification (6 steps) — COMPLETED
- [x] Phase 4 — Auth: Registration & Password Reset (5 steps) — COMPLETED
- [x] Phase 5 — User Dashboard & Profile (3 steps) — COMPLETED
- [x] Phase 6 — Security, Password & Login History (5 steps) — COMPLETED
- [ ] Phase 7 — Support Ticket System (4 steps) — PENDING
- [ ] Phase 8 — Notifications, Popups & Final Polish (7 steps) — PENDING
