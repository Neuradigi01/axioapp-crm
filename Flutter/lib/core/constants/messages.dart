/// User-facing message strings.
///
/// Matches the Angular frontend's message constants pattern.
/// Only includes messages relevant to the Flutter user panel (no admin).
class Messages {
  Messages._();

  // ── Generic ───────────────────────────────────────────────────────
  static const String errorGeneric = 'An error occurred. Please try again.';
  static const String errorLoadFailed = 'Failed to load data. Please try again.';
  static const String noInternetConnection = 'No internet connection.';
  static const String requestTimeout = 'Request timed out. Please try again.';

  // ── Auth ──────────────────────────────────────────────────────────
  static const String loginFailed = 'Login failed';
  static const String registrationSuccess = 'Registration successful!';
  static const String registrationFailed = 'Registration failed';
  static const String passwordResetSent =
      "If this account exists, you'll receive a reset link.";
  static const String passwordResetSuccess = 'Password reset successful!';
  static const String passwordResetFailed = 'Reset failed';

  // ── Profile ───────────────────────────────────────────────────────
  static const String profileUpdated = 'Profile updated successfully';
  static const String profileUpdateFailed = 'Failed to update profile';
  static const String profileImageUpdated = 'Profile image updated!';
  static const String profileImageRemoved = 'Profile image removed!';

  // ── Password ──────────────────────────────────────────────────────
  static const String passwordChanged = 'Password changed successfully';
  static const String passwordChangeFailed = 'Failed to change password';

  // ── 2FA ───────────────────────────────────────────────────────────
  static const String tfaStatusFailed = 'Failed to load 2FA status';
  static const String tfaEnabled = 'Two-factor authentication enabled';
  static const String tfaDisabled = 'Two-factor authentication disabled';
  static const String tfaMethodChanged = '2FA method changed successfully';
  static const String tfaSetupFailed = 'Failed to setup authenticator';
  static const String tfaOtpSent = 'Verification code sent';
  static const String tfaOtpResent = 'OTP resent successfully';
  static const String tfaOtpSendFailed = 'Failed to send OTP';
  static const String tfaVerifyFailed = 'Verification failed';
  static const String tfaDisableFailed = 'Failed to disable 2FA';
  static const String tfaMethodChangeFailed = 'Failed to change method';
  static const String tfaCodeResendFailed = 'Failed to resend code';
  static const String tfaMethodSwitchFailed = 'Failed to switch method';
  static const String tfaCodeInvalid = 'Invalid verification code';
  static const String tfaCodeResent = 'Verification code resent';
  static const String tfaMethodSwitched = 'Verification method changed';

  // ── Action verification ───────────────────────────────────────────
  static const String actionVerifyFailed =
      'Verification failed. Please try again.';
  static const String actionVerifyOtpSent = 'Verification code sent';
  static const String actionVerifyOtpSendFailed =
      'Failed to send verification code';
  static const String actionVerifyCancelled = 'Action cancelled';

  // ── File upload ───────────────────────────────────────────────────
  static const String fileTypeNotAllowed = 'File type not allowed';
  static const String fileTooLarge = 'File too large';
  static const String fileMaxCount = 'Maximum attachments limit reached';

  // ── Tickets ───────────────────────────────────────────────────────
  static const String ticketComposed = 'Ticket submitted successfully';
  static const String ticketComposeFailed = 'Failed to submit ticket';
  static const String ticketReplySent = 'Reply sent successfully';
  static const String ticketReplyFailed = 'Failed to send reply';
  static const String ticketUploadFailed = 'Failed to upload attachments';
  static const String ticketStatusUpdated = 'Ticket status updated successfully';
  static const String ticketStatusUpdateFailed = 'Failed to update ticket status';

  // ── Contact verification ──────────────────────────────────────────
  static const String contactOtpSent = 'Verification code sent';
  static const String contactOtpSendFailed = 'Failed to send verification code';
  static const String emailVerified =
      'Email verified successfully! You can now login.';
  static const String emailVerifyFailed = 'Email verification failed';

  // ── Notifications ─────────────────────────────────────────────────
  static const String notificationsMarkedRead =
      'All notifications marked as read';

  // ── Access & session ──────────────────────────────────────────────
  static const String accessDenied =
      'Access denied. You do not have permission.';
  static const String sessionExpired =
      'Your session has expired. Please login again.';

  // ── Validation ────────────────────────────────────────────────────
  static const String fieldRequired = 'This field is required';
  static const String invalidEmail = 'Please enter a valid email address';
  static const String passwordTooShort = 'Password must be at least 8 characters';
  static const String passwordsDoNotMatch = 'Passwords do not match';
  static const String invalidPhoneNumber = 'Please enter a valid phone number';
}
