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
  // entirely (Sentry.init() is guarded on this in main.ts). The AIXO
  // deployment reports to AIXO's own Sentry account (project
  // `aixoapp-frontend`), separate from the Neuradigi project used by the
  // development + neuradigi builds.
  sentryDsn:
    'https://b36e9dea732eed650211176e9987c49c@o4512164209164288.ingest.us.sentry.io/4512164252745728',
  sentryEnvironment: 'production-aixoapp',
};
