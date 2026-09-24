export const environment = {
  production: true,
  apiBaseUrl: 'https://crm-api.aixoapp.com/api/v1',
  // Where the embeddable widget JS bundle is served from. Used by the
  // Settings → Embed tab to generate the install snippet. The API
  // serves the bundle via a StaticFiles mount at `/widget/v1/widget.js`
  // (see api/src/app/main.py); docker-compose mounts widget/dist into
  // the container at /app/widget.
  embedWidgetHost: 'https://crm-api.aixoapp.com/widget',
  // In-app debug console overlay (@neuradigi/debug-console). OFF in prod so the
  // console is never patched and nothing is mounted for end users.
  enableDebugConsole: false,
  // Sentry — write-only DSN, safe to commit. Empty string disables the SDK
  // entirely (Sentry.init() is guarded on this in main.ts). Distinct
  // environment tag per production deployment so aixoapp errors don't
  // get lumped with the neuradigi tenant's issues.
  sentryDsn:
    'https://68dd925b617841de4e49a400796b0e47@o4512140356354048.ingest.us.sentry.io/4512140605194240',
  sentryEnvironment: 'production-aixoapp',
};
