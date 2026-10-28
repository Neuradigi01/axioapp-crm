export interface DemoPreset {
  readonly label: string;
  readonly identifier: string;
  readonly password: string;
  readonly orgSlug: string;
}

/** Shape of `GET /api/v1/_dev/demo-logins` rows. Returned only when the
 * API container has `IS_DEVELOPMENT=true`; production deployments serve
 * an empty list (or 404), which collapses the pill to nothing. */
export interface DemoLoginResponseRow {
  label: string;
  identifier: string;
  password: string;
  org_slug: string;
  org_name: string;
}
