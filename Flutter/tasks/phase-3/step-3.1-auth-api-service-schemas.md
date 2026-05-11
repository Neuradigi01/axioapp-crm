# Step 3.1 — Auth API Service & Schemas

> **Status:** COMPLETED

> **Phase 3: Authentication — Login, 2FA & Email Verification**
> Read `Flutter/docs/CODING_STANDARDS.md` — "HTTP / API Standards" section.
> Read `Flutter/docs/COMPONENT_REFERENCE.md` — "Data Models (freezed)" section.

**Prerequisites:** Phase 2 complete (Step 2.9)

---

**What to do:**
1. Create `lib/services/auth_api_service.dart` — all auth API calls
2. Create `lib/schemas/auth_schema.dart` — request/response DTOs (freezed)
3. Create `lib/services/app_config_api_service.dart` — app config endpoint
4. Create `lib/schemas/app_config_schema.dart` — app config model
5. Run `build_runner` to generate freezed/json_serializable code

**Auth API Service methods:**
- `login(LoginRequest)` → ApiResponse
- `tryAnotherWay2fa(TryAnotherWayRequest)` → ApiResponse
- `forgotPassword(ForgotPasswordRequest)` → ApiResponse
- `resetPassword(ResetPasswordRequest)` → ApiResponse
- `verifyEmail(String token)` → ApiResponse
- `sendContactVerificationOtp(SendOtpRequest)` → ApiResponse

**Schemas (freezed):**
- `LoginRequest` — identifier, password, twoFactorCode?, captchaToken?, captchaAnswer?
- `LoginResponse` — token, userId, role, accessRights, requires2fa?, requiresEmailVerification?, availableMethods?, preferredMethod?, email?
- `TryAnotherWayRequest` — tempToken, method
- `AppConfig` — captchaEnabled, captchaType, captchaSiteKey, emailEnabled, smsEnabled, firebaseEnabled, contactVerificationMode, etc.

**Verify:**
- [ ] `flutter pub run build_runner build` succeeds
- [ ] All schemas generate `.freezed.dart` and `.g.dart` files
- [ ] API service methods compile
- [ ] Provider for AuthApiService registered in service_providers.dart

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
