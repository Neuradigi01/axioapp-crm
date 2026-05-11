# Step 6.3 — Login History API & Widget

> **Status:** COMPLETED

> **Phase 6: Security, Password & Login History**

**Prerequisites:** Step 6.2

---

**What to do:**
1. Create `lib/services/login_history_api_service.dart` — login history API calls
2. Create `lib/models/login_history.dart` — LoginHistoryRecord model (freezed)
3. Create `lib/schemas/login_history_schema.dart` — request DTOs
4. Create `lib/providers/login_history_provider.dart` — provider with pagination
5. Create `lib/features/shared/widgets/login_history_table_widget.dart` — table component
6. Run `build_runner`

**API methods:**
- `getList(LoginHistoryListRequest)` → ApiResponse (paginated)
- `logoutSession(LogoutSessionRequest)` → ApiResponse
- `logout()` → ApiResponse

**Model:**
- `LoginHistoryRecord` — id, date, ipAddress, city, country, device, os, browser, status, isCurrent, tokenId

**Table features:**
- Columns: Date, IP Address, Location (City, Country), Device, OS, Browser, Status, Action
- Pagination (uses AppPagination widget from Step 2.4)
- "Logout" button per row (except current session)
- Current session badge
- Device type icon (desktop/mobile/tablet)
- Status badge (Active/Expired)
- Map link for location (opens Google Maps)

**Verify:**
- [ ] Table loads paginated data
- [ ] Pagination controls work
- [ ] Logout session button works
- [ ] Current session highlighted
- [ ] Device icons correct
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
