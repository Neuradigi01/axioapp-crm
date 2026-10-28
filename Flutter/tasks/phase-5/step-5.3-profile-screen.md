# Step 5.3 — Profile Screen (View & Edit)

> **Status:** COMPLETED

> **Phase 5: User Dashboard & Profile**

**Prerequisites:** Step 5.2

---

**What to do:**
1. Create `lib/features/user/screens/profile_screen.dart`
2. Create `lib/features/user/widgets/profile_image_widget.dart` — circle avatar with upload/remove

**Profile screen features:**
- Form card with title "My Profile"
- User ID (read-only, non-editable field)
- First Name (editable)
- Last Name (editable)
- Email (editable)
- Mobile (editable)
- Country dropdown with search
- State dropdown (loads based on country)
- Referral ID (read-only)
- Joining Date (read-only)
- "Save Changes" button with loading state
- Success/error snackbar on save

**Profile Image widget (at top of form):**
- Large circle avatar showing profile image or initials
- Camera icon overlay button
- On tap: options — "Upload Photo" or "Remove Photo"
- Upload: opens file picker, calls uploadProfileImage API
- Remove: confirmation dialog, calls removeProfileImage API
- Loading spinner during upload

**Data flow:**
1. Screen loads → fetch profile from `userProfileProvider`
2. Populate form fields with current data
3. User edits → "Save Changes" calls updateProfile API
4. On success → refresh profile provider, show success snackbar

**Country/State pre-population:**
- On load, set country dropdown to user's current country
- Load states for that country
- Set state dropdown to user's current state

**Verify:**
- [ ] Profile loads and populates form
- [ ] Read-only fields are non-editable
- [ ] Country/State dropdowns work (search, load states)
- [ ] Save updates profile via API
- [ ] Profile image upload works
- [ ] Profile image remove works
- [ ] Success/error feedback shown
- [ ] Both themes look correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
