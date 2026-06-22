import { deriveApiOrigin } from '@app/core/services/url.util';

// Host (scheme + host + port) of the configured API, derived from
// `environment.apiBaseUrl` so the legacy template services hit the same
// backend as the rest of the app: the dev API under `ng serve`, the
// production API under a production build. Previously this was hardcoded
// to `http://localhost:8000`, which ignored the environment entirely.
const apiOrigin = deriveApiOrigin();

export const AppSettings = {
  ApiBaseUrl: `${apiOrigin}/api`,
  StaticBaseUrl: `${apiOrigin}/static`,
};
