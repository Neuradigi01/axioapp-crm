/// App-wide constants — page sizes, timeouts, limits, storage keys, etc.
class AppConstants {
  AppConstants._();

  // ── App info ──────────────────────────────────────────────────────
  static const String appName = 'Template App';

  // ── Roles ─────────────────────────────────────────────────────────
  static const String roleUser = 'User';
  static const String roleAdmin = 'Admin';

  // ── Pagination ────────────────────────────────────────────────────
  static const int defaultPageSize = 10;
  static const int maxPageSize = 50;

  // ── OTP ───────────────────────────────────────────────────────────
  static const int otpLength = 6;
  static const int otpExpirySeconds = 300;
  static const int resendCooldownSeconds = 30;

  // ── File upload ───────────────────────────────────────────────────
  static const int maxFileUploadCount = 5;
  static const int maxFileUploadSizeBytes = 10 * 1024 * 1024; // 10 MB
  static const List<String> allowedFileExtensions = [
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp',
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv',
    'txt', 'rtf', 'zip', 'rar',
  ];

  // ── Storage keys ──────────────────────────────────────────────────
  static const String storageKeyToken = 'auth_token';
  static const String storageKeyRefreshToken = 'refresh_token';
  static const String storageKeyTheme = 'app_theme';
  static const String storageKeyFcmToken = 'fcm_token';

  // ── Theme ─────────────────────────────────────────────────────────
  static const String themeLight = 'light';
  static const String themeDark = 'dark';

  // ── Snackbar ──────────────────────────────────────────────────────
  static const int snackbarDurationMs = 4000;
  static const int snackbarDurationLongMs = 6000;

  // ── Action verification ───────────────────────────────────────────
  static const String actionTokenHeader = 'X-Action-Token';
  static const String action2faErrorCode = '2FA_REQUIRED';

  // ── 2FA method keys ───────────────────────────────────────────────
  static const String tfaMethodAuthenticator = 'authenticator';
  static const String tfaMethodEmail = 'email';
  static const String tfaMethodSms = 'sms';

  static const Map<String, String> tfaMethodLabels = {
    tfaMethodAuthenticator: 'Authenticator App',
    tfaMethodEmail: 'Email OTP',
    tfaMethodSms: 'SMS OTP',
  };

  // ── Ticket status ─────────────────────────────────────────────────
  static const String ticketStatusOpen = 'Open';
  static const String ticketStatusInProgress = 'In Progress';
  static const String ticketStatusResolved = 'Resolved';
  static const String ticketStatusClosed = 'Closed';

  static const List<String> ticketStatusOptions = [
    ticketStatusOpen,
    ticketStatusInProgress,
    ticketStatusResolved,
    ticketStatusClosed,
  ];

  // ── Ticket priority ───────────────────────────────────────────────
  static const String priorityLow = 'Low';
  static const String priorityNormal = 'Normal';
  static const String priorityHigh = 'High';
  static const String priorityUrgent = 'Urgent';

  static const List<String> ticketPriorityOptions = [
    priorityLow,
    priorityNormal,
    priorityHigh,
    priorityUrgent,
  ];
}
