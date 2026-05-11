# Step 8.1 — App Initialization (Dynamic Routes + App Config)

> **Status:** PENDING

> **Phase 8: Notifications, Popups & Final Polish**

**Prerequisites:** Phase 6 + Phase 7 complete

---

**What to do:**
1. Create `lib/services/routes_api_service.dart` — routes config API
2. Create `lib/models/route_config.dart` — RouteConfig model (freezed)
3. Update `lib/core/services/routes_helper_service.dart` — populate from API data
4. Update `lib/main.dart` — load routes + app config on startup before rendering app
5. Create `lib/providers/app_config_provider.dart` — provider for app config
6. Run `build_runner`

**App startup flow:**
1. Initialize Flutter bindings
2. Initialize SharedPreferences
3. Check if user has saved token (auto-login check)
4. Fetch app config from `/api/app-config`
5. Fetch routes config from `/api/routes/config`
6. Populate RoutesHelper with loaded routes
7. Launch app with initial route based on auth state

**RoutesHelper features:**
- `loadRoutes(List<RouteConfig>)` — populate route map
- `getPath(String controlId)` — get path for control ID
- `getMenuItems(String role, String accessRights)` — build sidebar menu

**Dynamic drawer menu:**
- Update AppDrawer to use `RoutesHelper.getMenuItems()` instead of hardcoded list
- Menu items: icon, label, path, children (sub-items), order
- Only show items the user has access to (based on `accessRights`)

**Verify:**
- [ ] Routes load from API on startup
- [ ] App config cached in provider
- [ ] RoutesHelper returns correct paths
- [ ] Drawer menu is dynamic based on access rights
- [ ] Auto-login works (if token exists and valid)
- [ ] Graceful handling if API unreachable on startup

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
