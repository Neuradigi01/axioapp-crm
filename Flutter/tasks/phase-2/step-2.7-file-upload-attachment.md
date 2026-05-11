# Step 2.7 — File Upload & Attachment Widgets

> **Status:** COMPLETED

> **Phase 2: Shared Widgets & Layouts**

**Prerequisites:** Step 2.6

---

**What to do:**
1. Create `lib/shared/widgets/app_file_upload.dart` — file picker button with selected file list, remove capability
2. Create `lib/shared/widgets/app_attachment_list.dart` — display list of attachments with download action

**File Upload:**
- "Attach Files" button opens file picker
- Shows selected file names with remove (X) button
- Max 5 files, max 10MB per file
- Validates file size on selection
- `onFilesChanged(List<File>)` callback

**Attachment List:**
- Displays file name, size
- Download button per attachment
- Opens file in browser/viewer

**Verify:**
- [ ] File picker opens and selects files
- [ ] File size validation works
- [ ] Remove button removes file from list
- [ ] Attachment list renders correctly
- [ ] Works on both mobile and desktop

---

## Completion

This step is already completed. No action needed.


