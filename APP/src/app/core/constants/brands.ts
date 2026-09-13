/**
 * Brand definitions — one codebase, several brands.
 *
 * The product ships to more than one brand (Neuradigi's own CRM and the
 * AIXO white-label). Every brand runs the SAME build against the SAME API;
 * only the name and the imagery differ. Keeping that difference in data here,
 * rather than in a forked repository, is what stops the two drifting apart —
 * a fork of this app existed until 2026-09-13 and its entire divergence from
 * the original had decayed to one `<img>` src.
 *
 * Resolution is by hostname AT RUNTIME, not by a build configuration. Two
 * reasons:
 *
 *   1. One artifact serves both brands. nginx points a second `server_name`
 *      at the same root and the page brands itself — no second build, no
 *      second deploy target, no chance of shipping the wrong bundle to a
 *      domain.
 *   2. Angular REPLACES arrays when configurations are composed rather than
 *      merging them. A build-time brand would mean `fileReplacements` in both
 *      the environment and the brand configuration, and
 *      `--configuration development,aixo` would silently drop the environment
 *      swap — producing a local build pointed at the production API, with
 *      every log line reporting success.
 *
 * Assets live under `public/brands/<id>/`, except the default brand's, which
 * stay at the `public/` root so the favicon and manifest a browser requests
 * BEFORE Angular boots resolve to something real.
 */
export interface Brand {
  /** Stable identifier. Used for asset paths; never shown to a user. */
  readonly id: string;
  /** Product name as a user sees it — page title, org-name fallback, copy. */
  readonly name: string;
  /** Legal entity behind the brand, for notices and legal pages. */
  readonly legalName: string;
  /** Logo shown on the accounts pages. Path is relative to the app root. */
  readonly logoUrl: string;
  /** Favicon swapped in at boot. */
  readonly faviconUrl: string;
  /** PWA manifest swapped in at boot. */
  readonly manifestUrl: string;
  /**
   * Hostnames this brand answers on. Matched case-insensitively against
   * `location.hostname`, which never includes a port — so `localhost:4207`
   * matches `localhost`. Anything unmatched falls back to `DEFAULT_BRAND`,
   * which is why local development, preview URLs and bare IPs all render the
   * default brand without needing to be listed.
   */
  readonly hostnames: readonly string[];
}

/** Neuradigi's own CRM — the default brand and the fallback for any host. */
export const BRAND_NEURADIGI: Brand = {
  id: 'neuradigi',
  name: 'Neuradigi CRM',
  legalName: 'Neuradigi',
  logoUrl: 'images/Logo.svg',
  faviconUrl: 'favicon.ico',
  manifestUrl: 'manifest.webmanifest',
  hostnames: ['crm.neuradigi.com'],
};

/** AIXO white-label — same product, AIXO's name and imagery. */
export const BRAND_AIXO: Brand = {
  id: 'aixo',
  name: 'AIXO CRM',
  legalName: 'AIXO',
  logoUrl: 'brands/aixo/Logo.png',
  faviconUrl: 'brands/aixo/favicon.ico',
  manifestUrl: 'brands/aixo/manifest.webmanifest',
  hostnames: ['crm.aixoapp.com'],
};

export const BRANDS: readonly Brand[] = [BRAND_NEURADIGI, BRAND_AIXO];

export const DEFAULT_BRAND: Brand = BRAND_NEURADIGI;

/**
 * Pick the brand for a hostname, falling back to the default.
 *
 * Deliberately total — it cannot fail and cannot return null. An unknown host
 * is the normal case during development and on any preview or staging URL, and
 * a brandless app has nothing sensible to render.
 */
export function resolveBrand(hostname: string): Brand {
  const host = hostname.trim().toLowerCase();
  return BRANDS.find((brand) => brand.hostnames.includes(host)) ?? DEFAULT_BRAND;
}
