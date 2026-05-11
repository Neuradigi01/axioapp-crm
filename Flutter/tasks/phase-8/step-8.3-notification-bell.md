# Step 8.3 — Notification Bell & List

> **Status:** PENDING

> **Phase 8: Notifications, Popups & Final Polish**

**Prerequisites:** Step 8.2

---

**What to do:**
1. Create `lib/shared/widgets/notification_bell_widget.dart` — bell icon with unread count badge
2. Create `lib/features/user/screens/notifications_screen.dart` — notification list page (optional — or show in dropdown)

**Notification Bell (in AppBar):**
- Bell icon
- Red badge with unread count (hidden if 0)
- On tap: show dropdown/bottom sheet with recent notifications, or navigate to notifications page
- Fetches unread count on init and periodically

**Notification List (dropdown or page):**
- List of notifications with title, message, date, read/unread indicator
- Tap to mark as read
- "Mark All as Read" button
- Pagination if full page

**Verify:**
- [ ] Bell shows unread count
- [ ] Notifications load from API
- [ ] Mark as read updates badge count
- [ ] Mark all as read works
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
