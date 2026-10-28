# Step 7.3 — Compose Ticket Screen

> **Status:** PENDING

> **Phase 7: Support Ticket System**

**Prerequisites:** Step 7.2

---

**What to do:**
1. Create `lib/features/shared/screens/compose_ticket_screen.dart`

**Features:**
- Title: "New Support Ticket"
- Subject field (required)
- Message field (required, multiline, 5+ rows)
- File attachment section (AppFileUpload widget from Step 2.7)
  - Max 5 files, max 10MB each
  - Files uploaded individually to API, stored names collected
- "Submit" button with loading state
- "Cancel" button → go back

**Submission flow:**
1. Validate form
2. Upload each file via `uploadAttachment` API → collect stored names
3. Call `compose` API with subject, message, attachment stored names
4. Success → navigate back to ticket list, show success snackbar
5. Failure → show error message

**Verify:**
- [ ] Form validates required fields
- [ ] File picker allows multiple files
- [ ] File size validation (10MB max)
- [ ] Files upload before form submission
- [ ] Upload progress shown
- [ ] Successful submit navigates back
- [ ] Error handling for file upload failures
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
