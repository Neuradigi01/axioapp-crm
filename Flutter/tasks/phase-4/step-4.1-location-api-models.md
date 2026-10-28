# Step 4.1 — Location API Service & Models

> **Status:** COMPLETED

> **Phase 4: Authentication — Registration & Password Reset**

**Prerequisites:** Phase 3 complete (Step 3.6)

---

**What to do:**
1. Create `lib/services/location_api_service.dart` — country/state API calls
2. Create `lib/models/location.dart` — Country and State models (freezed)
3. Create `lib/providers/location_provider.dart` — providers for countries and states
4. Run `build_runner`

**API methods:**
- `getCountries()` → ApiResponse (list of countries)
- `getStates(int countryId)` → ApiResponse (list of states for country)

**Models:**
- `Country` — id, name, code, phoneCode
- `StateModel` — id, name, countryId

**Verify:**
- [ ] Models generate correctly
- [ ] Providers compile
- [ ] Country provider fetches and caches list
- [ ] State provider fetches based on country ID

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
