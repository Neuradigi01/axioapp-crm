"""One-shot: create or update the Mailgun inbound Route for this deploy.

Reads three env vars:

  * ``MAILGUN_API_KEY``      — private API key (from Mailgun Settings
                                 → API Keys).
  * ``MAILGUN_DOMAIN``       — receiving domain (sandbox subdomain in
                                 dev, ``reply.neuradigi.com`` in prod).
  * ``MAILGUN_WEBHOOK_URL``  — full HTTPS URL Mailgun POSTs each
                                 inbound to (must be reachable from
                                 Mailgun's public egress IPs).

The Route uses **``forward(<webhook_url>)``, not ``store()``** — the
store action would return a URL our server has to GET, which opens
an SSRF surface. Forward posts the full payload inline so we can
process it end-to-end without a callback.

Idempotency: lists existing routes, finds one whose expression
matches ``match_recipient(".*@<MAILGUN_DOMAIN>")``, and either
PUT-updates it or POST-creates a new one. Re-running the script
never duplicates the route.

Prod-domain safeguard: if the target domain looks production-shaped
(``reply.*`` without ``sandbox`` in the name) and the deploy env
isn't marked ``prod`` (via ``ENV_NAME=prod``), the script prompts
for an explicit ``CONFIRM`` before mutating — closes the "dev
operator accidentally re-pointed the prod route at their laptop"
foot-gun (Absence B5 finding from PLANNING_RULES review).

Usage:
    API\\run.cmd exec-shell api "python -m src.app.scripts.mailgun_route_setup"

Or inside a shell with SOPS env active:
    python -m src.app.scripts.mailgun_route_setup
"""

from __future__ import annotations

import os
import sys

import httpx


MAILGUN_API_BASE = "https://api.mailgun.net/v3"


def _die(message: str, exit_code: int = 1) -> None:
    """Print + exit. Keeps the script single-file + shell-friendly."""
    print(f"[mailgun-route-setup] ERROR: {message}", file=sys.stderr)
    sys.exit(exit_code)


def _load_required_env() -> tuple[str, str, str]:
    """Return ``(api_key, domain, webhook_url)`` or exit with a clear
    error listing whichever vars are missing."""
    missing: list[str] = []
    api_key = os.environ.get("MAILGUN_API_KEY", "").strip()
    domain = os.environ.get("MAILGUN_DOMAIN", "").strip()
    webhook_url = os.environ.get("MAILGUN_WEBHOOK_URL", "").strip()
    if not api_key:
        missing.append("MAILGUN_API_KEY")
    if not domain:
        missing.append("MAILGUN_DOMAIN")
    if not webhook_url:
        missing.append("MAILGUN_WEBHOOK_URL")
    if missing:
        _die(
            "missing env var(s): "
            + ", ".join(missing)
            + ". Add MAILGUN_API_KEY via `run.cmd secrets-edit` and "
            "MAILGUN_DOMAIN + MAILGUN_WEBHOOK_URL to config.env, "
            "then re-run inside `run.cmd shell api`."
        )
    return api_key, domain, webhook_url


def _guard_prod_domain(domain: str) -> None:
    """Prompt for confirmation if we're about to mutate a prod-looking
    route from a non-prod env. ``ENV_NAME=prod`` (Docker overlay sets
    this) waives the prompt."""
    looks_prod = domain.startswith("reply.") and "sandbox" not in domain
    if not looks_prod:
        return
    env_name = os.environ.get("ENV_NAME", "unknown").strip().lower()
    if env_name == "prod":
        return
    print(
        f"[mailgun-route-setup] SAFEGUARD: about to mutate route on "
        f"prod-looking domain {domain!r} from env {env_name!r}."
    )
    print("[mailgun-route-setup] Type CONFIRM (uppercase) to proceed, anything else to abort.")
    reply = sys.stdin.readline().strip()
    if reply != "CONFIRM":
        print("[mailgun-route-setup] Aborted by operator.")
        sys.exit(2)


def _build_expression(domain: str) -> str:
    """``match_recipient`` on any address at our receiving domain."""
    # ``.*`` matches every local part — the token-existence check
    # happens server-side in the ingest task, not at Mailgun.
    escaped = domain.replace(".", r"\.")
    return f'match_recipient(".*@{escaped}")'


def _build_actions(webhook_url: str) -> list[str]:
    """Forward the raw payload + attachments to our webhook, then
    stop processing. ``stop()`` prevents Mailgun's implicit
    fall-through to any lower-priority route."""
    return [f'forward("{webhook_url}")', "stop()"]


def _find_matching_route(
    client: httpx.Client, *, expression: str
) -> dict[str, object] | None:
    """List every existing route (paginated) and return the one whose
    expression matches ours, or None."""
    # Mailgun caps ``limit`` at 1000; well past our per-account count.
    resp = client.get("/routes", params={"limit": 1000})
    resp.raise_for_status()
    body = resp.json()
    items = body.get("items") or []
    for route in items:
        if route.get("expression") == expression:
            return route
    return None


def _upsert_route(
    client: httpx.Client,
    *,
    existing: dict[str, object] | None,
    domain: str,
    expression: str,
    actions: list[str],
) -> tuple[str, str]:
    """Create or update. Returns ``(route_id, verb)`` where verb is
    ``"created"`` or ``"updated"``."""
    payload = {
        "priority": 0,
        "description": f"CRM inbound reply-capture for {domain}",
        "expression": expression,
        "action": actions,
    }
    if existing is not None:
        route_id = str(existing["id"])
        resp = client.put(f"/routes/{route_id}", data=payload)
        resp.raise_for_status()
        return route_id, "updated"
    resp = client.post("/routes", data=payload)
    resp.raise_for_status()
    route_id = str(resp.json()["route"]["id"])
    return route_id, "created"


def main() -> None:
    api_key, domain, webhook_url = _load_required_env()
    _guard_prod_domain(domain)

    expression = _build_expression(domain)
    actions = _build_actions(webhook_url)

    print(f"[mailgun-route-setup] domain      = {domain}")
    print(f"[mailgun-route-setup] webhook_url = {webhook_url}")
    print(f"[mailgun-route-setup] expression  = {expression}")
    print(f"[mailgun-route-setup] actions     = {actions}")

    with httpx.Client(
        auth=("api", api_key),
        base_url=MAILGUN_API_BASE,
        timeout=30.0,
    ) as client:
        try:
            existing = _find_matching_route(client, expression=expression)
        except httpx.HTTPStatusError as exc:
            _die(
                "Mailgun rejected the routes-list request: "
                f"{exc.response.status_code} {exc.response.text[:200]}. "
                "Check MAILGUN_API_KEY is a private (not public / verification) key."
            )
        except httpx.HTTPError as exc:
            _die(f"could not reach Mailgun API: {exc}")

        try:
            route_id, verb = _upsert_route(
                client,
                existing=existing,
                domain=domain,
                expression=expression,
                actions=actions,
            )
        except httpx.HTTPStatusError as exc:
            _die(
                f"Mailgun rejected the upsert: {exc.response.status_code} "
                f"{exc.response.text[:200]}"
            )
        except httpx.HTTPError as exc:
            _die(f"Mailgun request failed: {exc}")

    print(f"[mailgun-route-setup] Route {verb}: id={route_id}")
    print(
        "[mailgun-route-setup] Verify in the Mailgun dashboard "
        "(Send → Receiving → Routes)."
    )


if __name__ == "__main__":
    main()
