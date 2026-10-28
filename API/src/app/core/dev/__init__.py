"""Dev-only routes. Mounted from `main.py` only when
`IS_DEVELOPMENT=true` is set on the API container.

The single endpoint today is `/api/v1/_dev/demo-logins` which backs
the login page's "Test logins" dropdown. Lives here so production
builds (which don't set that env) never even resolve the route.
"""
