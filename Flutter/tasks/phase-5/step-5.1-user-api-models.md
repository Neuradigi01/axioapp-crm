# Step 5.1 — User API Service & Models

> **Status:** COMPLETED

> **Phase 5: User Dashboard & Profile**

**Prerequisites:** Phase 4 complete (Step 4.5)

---

**What to do:**
1. Create `lib/services/user_api_service.dart` — user API calls
2. Create `lib/models/user_profile.dart` — UserProfile model (freezed)
3. Create `lib/models/dashboard_data.dart` — DashboardData model (freezed)
4. Create `lib/schemas/user_schema.dart` — ProfileUpdateRequest DTO
5. Create `lib/providers/user_provider.dart` — providers for dashboard and profile
6. Run `build_runner`

**User API Service methods:**
- `getDashboard()` → ApiResponse
- `getProfile()` → ApiResponse
- `updateProfile(ProfileUpdateRequest)` → ApiResponse
- `uploadProfileImage(String filePath)` → ApiResponse
- `removeProfileImage()` → ApiResponse

**Models:**
- `UserProfile` — userId, firstName, lastName, email, mobile, country, state, countryId, stateId, profileImage, referralId, joiningDate
- `DashboardData` — referralCount, openTickets, twoFactorEnabled, accountStatus, firstName, lastName, profileImage

**Verify:**
- [ ] Models generate correctly via build_runner
- [ ] API service compiles
- [ ] Providers registered

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
