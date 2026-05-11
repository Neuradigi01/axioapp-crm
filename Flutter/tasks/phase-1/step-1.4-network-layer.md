# Step 1.4 — Network Layer (Dio + ApiHelper + Interceptors)

> **Status:** COMPLETED

> **Phase 1: Project Setup & Core Infrastructure**
> Read `Flutter/docs/COMPONENT_REFERENCE.md` — "HTTP / Network Layer" and "Action Verification" sections.

**Prerequisites:** Step 1.3

---

**What to do:**
1. Create `lib/core/network/api_response.dart` — ApiResponse model
2. Create `lib/core/network/api_helper.dart` — Dio wrapper (get, post, put, delete, uploadFile)
3. Create `lib/core/network/auth_interceptor.dart` — attach JWT token, handle 401 (logout), handle basic 403
4. Create `lib/core/network/action_verify_interceptor.dart` — **CRITICAL: Reusable 2FA interceptor** (catches 403 + `2FA_REQUIRED`, shows dialog, retries request with `X-Action-Token` header). See `COMPONENT_REFERENCE.md` "Action Verification" section for exact flow.
5. Create `lib/core/network/error_interceptor.dart` — global error handling, logging
6. Create `lib/core/network/dio_provider.dart` — Dio instance configuration (base URL, timeouts, interceptors). Interceptor order: AuthInterceptor → ActionVerifyInterceptor → ErrorInterceptor
7. Create `lib/providers/service_providers.dart` — Riverpod providers for Dio, ApiHelper, API services

**ApiResponse must match backend format:**
```dart
{ success: bool, message: String, data: dynamic, dataCount: int? }
```

**Action Verify Interceptor flow:**
1. API returns 403 with `error_code: "2FA_REQUIRED"` on ANY endpoint
2. Interceptor catches this, calls `ActionVerifyService.getActionToken()`
3. Service shows modal dialog → user enters 2FA code → returns action_token
4. Interceptor retries the ORIGINAL request with `X-Action-Token` header
5. Calling code never knows 2FA happened (completely transparent)

**Verify:**
- [ ] ApiHelper compiles with all CRUD methods
- [ ] AuthInterceptor adds Bearer token from secure storage
- [ ] 401 response triggers logout flow
- [ ] ActionVerifyInterceptor catches 403 + 2FA_REQUIRED (stub dialog for now, full UI in Step 2.6)
- [ ] Dio configured with base URL from AppConfig
- [ ] All providers compile

---

## Completion

This step is already completed. No action needed.


