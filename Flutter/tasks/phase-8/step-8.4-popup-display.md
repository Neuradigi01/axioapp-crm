# Step 8.4 — Popup Display

> **Status:** PENDING

> **Phase 8: Notifications, Popups & Final Polish**

**Prerequisites:** Step 8.3

---

**What to do:**
1. Create `lib/services/popup_api_service.dart` — active popup API
2. Create `lib/models/popup.dart` — Popup model (freezed)
3. Create `lib/shared/widgets/popup_display_widget.dart` — modal popup on dashboard load
4. Run `build_runner`

**Popup features:**
- On dashboard load: check for active popups via API
- If popup exists: show as modal dialog
- Popup content: title, message (may include HTML — render as plain text or use flutter_html if needed)
- "Close" button
- "Don't show again" option (stored locally)
- Only show once per session (or per popup ID)

**Verify:**
- [ ] Popup loads from API on dashboard entry
- [ ] Modal displays with content
- [ ] Close button dismisses
- [ ] "Don't show again" persists
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
