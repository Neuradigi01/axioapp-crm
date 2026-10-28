/// Application configuration — environment settings.
///
/// Pass via: `flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api`
class AppConfig {
  AppConfig._();

  // ── API Configuration ─────────────────────────────────────────────
  // Defaults to Android emulator localhost alias
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:30005/api',
  );

  // ── WebSocket Configuration ───────────────────────────────────────
  // Defaults to Android emulator localhost alias
  static const String wsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL',
    defaultValue: 'ws://10.0.2.2:30005/ws',
  );

  // ── App info ──────────────────────────────────────────────────────
  static const String appName = 'Template App';

  // ── Timeouts ──────────────────────────────────────────────────────
  static const int requestTimeoutMs = 30000;
  static const int connectTimeoutMs = 15000;
}
