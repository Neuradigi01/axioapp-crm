# Step 6.1 — Two-Factor API Service & Models

> **Status:** COMPLETED

> **Phase 6: Security, Password & Login History**

**Prerequisites:** Phase 5 complete (Step 5.3)

---

**What to do:**
1. Create `lib/services/two_factor_api_service.dart` — 2FA management API calls
2. Create `lib/services/action_verify_api_service.dart` — action verification API calls (if not already created in Step 2.6)
3. Create `lib/models/tfa_status.dart` — TfaStatus model (freezed)
4. Create `lib/schemas/tfa_schema.dart` — 2FA request DTOs
5. Create `lib/schemas/action_verify_schema.dart` — action verification DTOs
6. Create `lib/providers/tfa_provider.dart` — provider for 2FA status
7. Run `build_runner`

**2FA API methods:**
- `getStatus()` → ApiResponse (current 2FA status, method, enabled)
- `setupAuthenticator()` → ApiResponse (QR code URL, secret key)
- `sendSetupOtp(SendSetupOtpRequest)` → ApiResponse
- `verifyAndEnable(VerifyAndEnableRequest)` → ApiResponse
- `disable(DisableRequest)` → ApiResponse
- `changeMethod(ChangeMethodRequest)` → ApiResponse

**Action Verify API methods:**
- `sendOtp(ActionVerifySendOtpRequest)` → ApiResponse
- `verify(ActionVerifyRequest)` → ApiResponse (returns action token)

**Models:**
- `TfaStatus` — isEnabled, method, email (masked), mobile (masked), hasAuthenticator

**Verify:**
- [ ] All models generate correctly
- [ ] API services compile
- [ ] Providers registered

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
