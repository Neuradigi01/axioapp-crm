/// API endpoint path constants.
///
/// All paths are relative to [AppConfig.apiBaseUrl].
/// Matches the FastAPI backend route structure.
class ApiEndpoints {
  ApiEndpoints._();

  // ── Auth ──────────────────────────────────────────────────────────
  static const String login = '/auth/login';
  static const String register = '/auth/register';
  static const String captcha = '/auth/captcha';
  static const String forgotPassword = '/auth/forgot-password';
  static const String resetPassword = '/auth/reset-password';
  static const String tfaTryAnotherWay = '/auth/2fa-try-another-way';
  static const String verifyContactSendOtp = '/auth/verify-contact/send-otp';
  static const String verifyContactVerifyEmail =
      '/auth/verify-contact/verify-email';

  // ── User ──────────────────────────────────────────────────────────
  static const String userProfile = '/user/profile';
  static const String userProfileImage = '/user/profile/image';
  static const String userDashboard = '/user/dashboard';

  // ── Common (shared between user/admin) ────────────────────────────
  static const String changePassword = '/change-password';
  static const String logout = '/login-history/logout';

  // ── Action verification ───────────────────────────────────────────
  static const String actionVerifySendOtp = '/action-verify/send-otp';
  static const String actionVerify = '/action-verify';

  // ── Two-factor ────────────────────────────────────────────────────
  static const String tfaStatus = '/two-factor/status';
  static const String tfaSetupAuthenticator = '/two-factor/setup-authenticator';
  static const String tfaSendSetupOtp = '/two-factor/send-setup-otp';
  static const String tfaVerifyAndEnable = '/two-factor/verify-and-enable';
  static const String tfaDisable = '/two-factor/disable';
  static const String tfaChangeMethod = '/two-factor/change-method';

  // ── Login history ─────────────────────────────────────────────────
  static const String loginHistoryList = '/login-history/list';
  static const String loginHistoryLogoutSession =
      '/login-history/logout-session';

  // ── Tickets ───────────────────────────────────────────────────────
  static const String ticketCompose = '/tickets/compose';
  static const String ticketList = '/tickets/list';
  static String ticketDetail(int ticketId) => '/tickets/$ticketId';
  static String ticketReply(int ticketId) => '/tickets/$ticketId/reply';
  static String ticketStatus(int ticketId) => '/tickets/$ticketId/status';

  // ── Attachments ───────────────────────────────────────────────────
  static const String attachmentUpload = '/attachments/upload';
  static String attachmentDownload(String storedName) =>
      '/attachments/$storedName';

  // ── Location ──────────────────────────────────────────────────────
  static const String countries = '/location/countries';
  static String states(int countryId) =>
      '/location/countries/$countryId/states';

  // ── Notifications ─────────────────────────────────────────────────
  static String notificationRead(int notificationId) =>
      '/notifications/$notificationId/read';
  static const String notificationsMarkAllRead = '/notifications/mark-all-read';

  // ── Device tokens (FCM) ───────────────────────────────────────────
  static const String deviceTokenRegister = '/device-tokens/register';
  static const String deviceTokenUnregister = '/device-tokens/unregister';

  // ── Content ───────────────────────────────────────────────────────
  static const String newsActive = '/news/active';
  static const String popupsActive = '/popups/active';

  // ── Routes config ─────────────────────────────────────────────────
  static const String routesConfig = '/routes/config';

  // ── App config ────────────────────────────────────────────────────
  static const String appConfig = '/app-config';

  // ── Utils ─────────────────────────────────────────────────────────
  static const String qrCode = '/utils/qr';
}
