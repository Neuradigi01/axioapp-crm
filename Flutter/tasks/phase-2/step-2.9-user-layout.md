# Step 2.9 — User Layout Shell (Drawer + AppBar)

> **Status:** COMPLETED

> **Phase 2: Shared Widgets & Layouts**
> Read `Flutter/docs/COMPONENT_REFERENCE.md` — "Layout System" section.

**Prerequisites:** Step 2.8

---

**What to do:**
1. Create `lib/shared/layouts/user_layout.dart` — main user panel layout
2. Create `lib/shared/widgets/app_drawer.dart` — navigation drawer with dynamic menu
3. Create `lib/shared/widgets/user_menu_widget.dart` — profile dropdown in AppBar (Profile, Password, Security, Logout)
4. Create `lib/shared/widgets/theme_toggle_widget.dart` — icon button to toggle light/dark

**User Layout features:**
- AppBar with hamburger menu, page title, notification bell, profile menu, theme toggle
- Drawer with dynamic menu items (loaded from routes/access rights)
- Responsive: on large screens drawer can be persistent; on mobile, overlay
- Profile image display in AppBar (circle avatar, fallback to initials)
- Drawer shows user info at top (name, email, avatar)
- Active menu item highlighted
- Expandable menu sections (parent-child hierarchy)

**Profile Menu (dropdown):**
- Profile
- Change Password
- Security
- Divider
- Logout

**Verify:**
- [ ] Drawer opens and closes
- [ ] Menu items are dynamic (from a mock list for now)
- [ ] Active route is highlighted in drawer
- [ ] Profile dropdown shows all options
- [ ] Logout clears auth and navigates to login
- [ ] Theme toggle works from both AppBar and drawer
- [ ] Responsive behavior works (mobile vs desktop)
- [ ] Both themes look correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** PENDING
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
