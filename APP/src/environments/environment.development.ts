export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:30007/api/v1',
  embedWidgetHost: 'http://localhost:5173',
  // In-app debug console overlay (@neuradigi/debug-console). ON in dev so logs,
  // uncaught errors and rejections are visible without opening DevTools.
  enableDebugConsole: true,
  // Sentry — disabled for local dev. Empty DSN skips Sentry.init() in
  // main.ts; only the production builds (environment.ts,
  // environment.neuradigi.ts) carry a DSN.
  sentryDsn: '',
  sentryEnvironment: 'development',
};
