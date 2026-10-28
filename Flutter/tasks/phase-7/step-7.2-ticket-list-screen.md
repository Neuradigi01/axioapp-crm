# Step 7.2 — Ticket List Screen

> **Status:** PENDING

> **Phase 7: Support Ticket System**

**Prerequisites:** Step 7.1

---

**What to do:**
1. Create `lib/features/shared/screens/ticket_list_screen.dart`

**Features:**
- Title: "Support Tickets"
- "Compose" button in header (navigates to compose screen)
- **Filters:**
  - Search field (by subject or ticket ID)
  - Status dropdown (All, Open, In Progress, Resolved, Closed)
  - Priority dropdown (All, Low, Normal, High, Urgent)
- **Table/List:**
  - Columns: SR#, Subject, Status (badge), Priority (badge), Created Date, Last Reply, Replies
  - Tap row → navigate to view ticket
  - SR# auto-computed (page-aware serial number)
- **Pagination** (AppPagination widget from Step 2.4)
- Loading state while fetching
- Empty state: "No tickets found"
- Responsive: table on desktop, card list on mobile

**Data flow:**
1. On load → fetch tickets with default filters
2. Filter change → re-fetch from page 1
3. Page change → re-fetch with current filters

**Verify:**
- [ ] Ticket list loads from API
- [ ] Search filters results
- [ ] Status/Priority dropdowns filter correctly
- [ ] Pagination works
- [ ] Tap navigates to ticket detail
- [ ] Compose button navigates to compose
- [ ] Empty state shows when no results
- [ ] Status/Priority badges colored correctly
- [ ] Responsive layout works
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
