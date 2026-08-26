export const environment = {
  production: true,
  apiBaseUrl: 'https://crm-api.neuradigi.com/api/v1',
  // Where the embeddable widget JS bundle is served from. Used by the
  // Settings → Embed tab to generate the install snippet. The API
  // serves the bundle via a StaticFiles mount at `/widget/v1/widget.js`
  // (see api/src/app/main.py); docker-compose mounts widget/dist into
  // the container at /app/widget.
  embedWidgetHost: 'https://crm-api.neuradigi.com/widget',
  // In-app debug console overlay (@neuradigi/debug-console). OFF in prod so the
  // console is never patched and nothing is mounted for end users.
  enableDebugConsole: false,
};
