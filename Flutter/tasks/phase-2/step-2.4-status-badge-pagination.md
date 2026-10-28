# Step 2.4 — Status Badge & Pagination

> **Status:** COMPLETED

> **Phase 2: Shared Widgets & Layouts**

**Prerequisites:** Step 2.3

---

**What to do:**
1. Create `lib/shared/widgets/app_status_badge.dart` — colored chip/badge for statuses (Active, Inactive, Open, Closed, etc.)
2. Create `lib/shared/widgets/app_pagination.dart` — page controls (Previous, page numbers, Next, page size selector)

**Status Badge:**
- Takes `label` and `status` string
- Maps status to theme-aware color using `getStatusColor` helper
- Renders as small rounded chip

**Pagination:**
- `currentPage`, `totalPages`, `pageSize`, `onPageChanged`, `onPageSizeChanged`
- Shows: "< 1 2 3 ... 10 >" with current page highlighted
- Page size dropdown (5, 10, 25, 50)
- Shows total count: "Showing 1-10 of 47"

**Verify:**
- [ ] Status badge shows correct colors for different statuses
- [ ] Pagination navigates correctly
- [ ] Page size change resets to page 1
- [ ] Both work in light and dark theme

---

## Completion

This step is already completed. No action needed.


