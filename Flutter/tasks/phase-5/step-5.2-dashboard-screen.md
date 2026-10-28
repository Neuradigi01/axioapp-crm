# Step 5.2 — Dashboard Screen

> **Status:** COMPLETED

> **Phase 5: User Dashboard & Profile**

**Prerequisites:** Step 5.1

---

**What to do:**
1. Create `lib/features/user/screens/dashboard_screen.dart`
2. Create `lib/features/user/widgets/dashboard_tile_widget.dart` — metric tile card

**Dashboard features:**
- Greeting: "Welcome, [First Name]!" with profile image
- Dashboard tiles (grid):
  - Referral Count (icon: people)
  - Open Tickets (icon: support)
  - 2FA Status (icon: shield) — "Enabled" or "Disabled"
  - Account Status (icon: verified) — "Active"
- Each tile: icon, label, value, themed background
- Responsive grid: 2 columns on mobile, 4 on tablet/desktop
- Pulls data from `userDashboardProvider` (FutureProvider)
- Loading state while fetching
- Error state with retry

**Tile widget:**
- `icon`, `label`, `value`, `color` (optional)
- Card with subtle background tint
- Icon in circle on left, label + value on right

**Verify:**
- [ ] Dashboard loads data from API
- [ ] Tiles display with correct data
- [ ] Grid is responsive
- [ ] Loading spinner shows during fetch
- [ ] Error state shows retry button
- [ ] Profile image renders (or initials fallback)
- [ ] Both themes look correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
