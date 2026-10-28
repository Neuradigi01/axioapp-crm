# Step 7.4 — View Ticket Screen (Thread + Reply)

> **Status:** PENDING

> **Phase 7: Support Ticket System**

**Prerequisites:** Step 7.3

---

**What to do:**
1. Create `lib/features/shared/screens/view_ticket_screen.dart`
2. Create `lib/features/shared/widgets/ticket_thread_widget.dart` — message thread display

**View Ticket features:**
- **Header section:**
  - Subject
  - Status badge
  - Priority badge
  - Created date
- **Thread section:**
  - List of messages in chronological order
  - Each message: sender name, sender type badge (You/Admin), timestamp, message text, attachments
  - Your messages aligned right (or different background)
  - Admin messages aligned left
  - Attachments with download links (uses AppAttachmentList from Step 2.7)
- **Reply section (bottom):**
  - Message text field (multiline)
  - File attachment (AppFileUpload from Step 2.7)
  - "Send Reply" button with loading state

**Reply flow:**
1. Enter message (required)
2. Optionally attach files
3. Upload files → call reply API
4. Success → append to thread, clear reply form
5. Failure → show error

**Verify:**
- [ ] Ticket detail loads from API
- [ ] Header shows correct status, priority, dates
- [ ] Thread messages display in order
- [ ] User vs Admin messages visually distinct
- [ ] Attachments downloadable
- [ ] Reply sends and appends to thread
- [ ] File attachments on reply work
- [ ] Loading states on all actions
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
