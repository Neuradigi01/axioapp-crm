# Step 8.2 — Push Notifications (Firebase)

> **Status:** PENDING

> **Phase 8: Notifications, Popups & Final Polish**

**Prerequisites:** Step 8.1

---

**What to do:**
1. Create `lib/services/notification_api_service.dart` — notification + device token API
2. Create `lib/models/notification.dart` — AppNotification model (freezed)
3. Create `lib/core/services/push_notification_service.dart` — FCM setup + handling
4. Create `lib/providers/notification_provider.dart` — notification state
5. Run `build_runner`

**Note:** Firebase setup requires platform-specific configuration (google-services.json for Android, GoogleService-Info.plist for iOS). This step creates the Dart code; platform config is done manually.

**API methods:**
- `registerDeviceToken(String token)` → ApiResponse
- `unregisterDeviceToken(String token)` → ApiResponse
- `getNotifications(NotificationListRequest)` → ApiResponse (paginated)
- `getUnreadCount()` → ApiResponse
- `markAsRead(int notificationId)` → ApiResponse
- `markAllAsRead()` → ApiResponse

**PushNotificationService:**
- Request permission
- Get FCM token
- Register token with backend
- Handle foreground notifications (show local notification)
- Handle background/terminated notifications
- Handle notification tap (navigate to relevant screen)

**Verify:**
- [ ] FCM service initializes without errors
- [ ] Token registration API called
- [ ] Foreground notification shown as local notification
- [ ] Notification tap navigates correctly (stretch goal — needs deep linking)
- [ ] All models generate correctly

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
