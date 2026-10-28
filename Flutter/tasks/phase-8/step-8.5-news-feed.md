# Step 8.5 — News Feed (Dashboard)

> **Status:** PENDING

> **Phase 8: Notifications, Popups & Final Polish**

**Prerequisites:** Step 8.4

---

**What to do:**
1. Create `lib/services/news_api_service.dart` — active news API
2. Create `lib/models/news.dart` — News model (freezed)
3. Create `lib/features/user/widgets/dashboard_news_widget.dart` — news feed on dashboard
4. Run `build_runner`

**News feed features:**
- Section on dashboard below tiles
- Title: "Latest News"
- List of news items: title, summary, date
- Expandable/collapsible items (tap to read full text)
- Empty state if no news

**Verify:**
- [ ] News loads from API
- [ ] Items display correctly
- [ ] Expand/collapse works
- [ ] Empty state shown when no news
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
