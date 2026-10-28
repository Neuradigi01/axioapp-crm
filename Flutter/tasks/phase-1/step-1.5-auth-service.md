# Step 1.5 — Auth Service (Token Management)

> **Status:** COMPLETED

> **Phase 1: Project Setup & Core Infrastructure**

**Prerequisites:** Step 1.4

---

**What to do:**
1. Create `lib/core/services/auth_service.dart` — JWT token storage/retrieval/clear using flutter_secure_storage
2. Create `lib/core/services/routes_helper_service.dart` — dynamic route lookup (stub — will be populated on app init)
3. Create `lib/providers/auth_provider.dart` — AuthState + AuthNotifier (Riverpod StateNotifier)

**AuthService methods:**
- `saveToken(String token)`
- `getToken() → Future<String?>`
- `clearToken()`
- `saveUserData(Map<String, dynamic> data)` — saves userId, role, accessRights
- `getUserData() → Future<Map<String, String?>>`
- `clearAll()`
- `isAuthenticated → Future<bool>`

**AuthState fields:**
- `isAuthenticated`, `isLoading`, `token`, `userId`, `role`, `accessRights`, `errorMessage`

**Verify:**
- [ ] Token saved/read/cleared from flutter_secure_storage
- [ ] AuthNotifier login/logout methods work
- [ ] AuthState is immutable (freezed or manual)

---

## Completion

This step is already completed. No action needed.


