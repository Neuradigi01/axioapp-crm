# Step 2.2 — Feedback Widgets (Snackbar, Dialogs, Loading, Empty, Error)

> **Status:** COMPLETED

> **Phase 2: Shared Widgets & Layouts**

**Prerequisites:** Step 2.1

---

**What to do:**
1. Create `lib/shared/widgets/app_snackbar.dart` — helper function to show themed snackbar (success, error, info variants)
2. Create `lib/shared/widgets/app_confirm_dialog.dart` — Yes/No confirmation dialog
3. Create `lib/shared/widgets/app_loading_indicator.dart` — centered CircularProgressIndicator with optional message
4. Create `lib/shared/widgets/app_empty_state.dart` — icon + message for empty lists
5. Create `lib/shared/widgets/app_error_widget.dart` — error message + retry button

**AppSnackbar:**
```dart
AppSnackbar.show(context, message: 'Saved!', type: SnackbarType.success);
AppSnackbar.show(context, message: 'Failed', type: SnackbarType.error);
```

**AppConfirmDialog:**
```dart
final confirmed = await AppConfirmDialog.show(
  context, title: 'Confirm', message: 'Are you sure?',
);
```

**Verify:**
- [ ] Snackbar shows with correct color per type (success=green, error=red, info=blue)
- [ ] Confirm dialog returns true/false
- [ ] Loading, empty, error widgets render correctly
- [ ] All use theme tokens

---

## Completion

This step is already completed. No action needed.


