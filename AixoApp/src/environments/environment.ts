export const environment = {
  production: true,
  apiBaseUrl: 'https://crm-api.neuradigi.com/api/v1',
  // Where the embeddable widget JS bundle is served from. Used by the
  // Settings → Embed tab to generate the install snippet. Step 5 of
  // the embeddable-widget track ships the actual bundle.
  embedWidgetHost: 'http://localhost:5173',
  // In-app debug console overlay (@neuradigi/debug-console). OFF in prod so the
  // console is never patched and nothing is mounted for end users.
  enableDebugConsole: false,
};
