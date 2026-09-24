export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:30007/api/v1',
  embedWidgetHost: 'http://localhost:5173',
  // In-app debug console overlay (@neuradigi/debug-console). ON in dev so logs,
  // uncaught errors and rejections are visible without opening DevTools.
  enableDebugConsole: true,
  // Sentry — write-only DSN, safe to commit. Empty string disables the SDK
  // entirely (Sentry.init() is guarded on this in main.ts). Development tag
  // segregates dev noise from real user errors in the Sentry UI.
  sentryDsn:
    'https://68dd925b617841de4e49a400796b0e47@o4512140356354048.ingest.us.sentry.io/4512140605194240',
  sentryEnvironment: 'development',
};
