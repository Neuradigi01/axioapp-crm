/// Route name constants — control IDs matching the backend routes config.
///
/// These control IDs are used by [RoutesHelper] to resolve dynamic paths
/// loaded from the `/routes/config` endpoint.
class AppRoutes {
  AppRoutes._();

  // ── Auth routes (static, not from backend) ────────────────────────
  static const String login = 'login';
  static const String register = 'register';
  static const String forgotPassword = 'forgot_password';
  static const String resetPassword = 'reset_password';
  static const String twoFactorAuthentication = 'two_factor_authentication';
  static const String verifyEmail = 'verify_email';
  static const String emailVerificationNotice = 'email_verification_notice';

  // ── User panel routes (loaded from backend) ───────────────────────
  static const String userDashboard = 'user_dashboard';
  static const String userProfile = 'user_profile';
  static const String userSecurity = 'user_security';
  static const String userChangePassword = 'user_change_password';
  static const String userLoginHistory = 'user_login_history';

  // ── Support routes ────────────────────────────────────────────────
  static const String userSupport = 'user_support';
  static const String userTicketCompose = 'user_ticket_compose';
  static const String userTicketView = 'user_ticket_view';

  // ── Static path defaults (used before dynamic routes load) ────────
  static const String pathLogin = '/login';
  static const String pathRegister = '/register';
  static const String pathForgotPassword = '/forgot-password';
  static const String pathResetPassword = '/reset-password';
  static const String pathTwoFactor = '/two-factor';
  static const String pathVerifyEmail = '/verify-email';
  static const String pathEmailVerificationNotice = '/email-verification-notice';
  static const String pathDashboard = '/dashboard';
  static const String pathProfile = '/profile';
  static const String pathSecurity = '/security';
  static const String pathChangePassword = '/change-password';
  static const String pathLoginHistory = '/login-history';
  static const String pathSupport = '/support';
  static const String pathTicketCompose = '/support/compose';
  static const String pathTicketView = '/support/:ticketId';
}
