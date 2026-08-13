"""API Request node (``tasks/chatbot-builder`` Step 9 / Decision §16).

Sends one HTTP request through :mod:`core.chatbots.http_client_safe`
(SSRF-hardened) and captures a fragment of the response into the
run's ``context.api[node_id]`` so downstream nodes can reference
``{{api.<node_id>.field}}``.

Config shape::

    {
      "method": "POST",
      "url": "https://api.example.com/crm/enrich",
      "headers": {"Authorization": "Bearer ..."},
      "body_template": {"phone": "{{contact.phone}}"},
      "timeout_seconds": 10,
      "capture": {"industry": "$.company.industry", "score": "$.score"},
      "retry_on_5xx": 2
    }

Output ports: ``success`` (2xx / 3xx-post-redirect), ``error``
(any non-success or transport failure). Capture is a shallow map
of ``{alias: jsonpath}`` — v1 supports simple ``$.a.b.c`` shapes
(dot-path only, no ``[*]`` wildcards yet).
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

import httpx

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.http_client_safe import (
    SafeResponse,
    UnsafeUrl,
    request as safe_http_request,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "api_request"
_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_TIMEOUT = 10.0
_MAX_RETRY_ON_5XX = 3

logger = logging.getLogger(__name__)


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    method = str(cfg.get("method") or "GET").upper()
    url_template = str(cfg.get("url") or "")

    if method not in _ALLOWED_METHODS:
        return _shared.errored_result(
            f"api_request.method must be one of {sorted(_ALLOWED_METHODS)}"
        )
    if not url_template:
        return _shared.errored_result("api_request.url is required")

    # Interpolate {{variables}} in URL + headers + body before any
    # send. Same escape rules as the message nodes (control-strip
    # for JSON transport).
    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    channel = _shared.channel_of(ctx)

    url = channel_bridge.render_variables(
        url_template,
        run_context=ctx.run_context,
        contact_data=contact_data,
        channel=channel,
    )

    headers = _render_dict(
        cfg.get("headers") or {}, ctx=ctx, contact_data=contact_data, channel=channel
    )
    body_template = cfg.get("body_template")
    body: Any = None
    if body_template is not None:
        body = _render_body_template(
            body_template, ctx=ctx, contact_data=contact_data, channel=channel
        )

    timeout_seconds = float(cfg.get("timeout_seconds") or _DEFAULT_TIMEOUT)
    retry_on_5xx = int(cfg.get("retry_on_5xx") or 0)
    retry_on_5xx = max(0, min(retry_on_5xx, _MAX_RETRY_ON_5XX))

    if ctx.is_test:
        return NodeResult(
            next_edge_label="success",
            output={
                "method": method,
                "url": url,
                "headers": _redact_headers(headers),
                "body": body,
                "test_mode": True,
            },
        )

    last_response: SafeResponse | None = None
    last_error: str | None = None
    for attempt in range(retry_on_5xx + 1):
        try:
            last_response = await safe_http_request(
                method=method,
                url=url,
                headers=headers,
                json_body=body,
                timeout_seconds=timeout_seconds,
            )
        except UnsafeUrl as exc:
            return NodeResult(
                next_edge_label="error",
                skip_reason="unsafe_url",
                output={
                    "method": method,
                    "url": url,
                    "error": str(exc),
                },
            )
        except httpx.HTTPError as exc:
            last_error = str(exc)
            last_response = None
            continue

        if last_response.status_code >= 500 and attempt < retry_on_5xx:
            continue
        break

    if last_response is None:
        return NodeResult(
            next_edge_label="error",
            skip_reason="transport_failure",
            output={"method": method, "url": url, "error": last_error or "unknown"},
        )

    edge = "success" if last_response.status_code < 400 else "error"
    captured = _apply_captures(cfg.get("capture") or {}, last_response.json)

    api_scope = dict((ctx.run_context or {}).get("api") or {})
    api_scope[ctx.node_id] = {
        "status_code": last_response.status_code,
        "final_url": last_response.final_url,
        "truncated": last_response.truncated,
        **captured,
    }

    return NodeResult(
        next_edge_label=edge,
        context_patch={"api": api_scope},
        output={
            "method": method,
            "url": url,
            "status_code": last_response.status_code,
            "final_url": last_response.final_url,
            "captured": captured,
            "truncated": last_response.truncated,
        },
    )


# --- Helpers -------------------------------------------------------------


def _render_dict(
    src: dict[str, Any],
    *,
    ctx: NodeExecutionContext,
    contact_data: dict[str, Any] | None,
    channel: str,
) -> dict[str, str]:
    """Render every string value in ``src`` through the variable
    engine. Non-string values pass through as-is."""
    out: dict[str, str] = {}
    for k, v in src.items():
        if isinstance(v, str):
            out[str(k)] = channel_bridge.render_variables(
                v,
                run_context=ctx.run_context,
                contact_data=contact_data,
                channel=channel,
            )
        else:
            out[str(k)] = str(v)
    return out


def _render_body_template(
    template: Any,
    *,
    ctx: NodeExecutionContext,
    contact_data: dict[str, Any] | None,
    channel: str,
) -> Any:
    """Recursively render string leaves inside a dict/list body."""
    if isinstance(template, str):
        return channel_bridge.render_variables(
            template,
            run_context=ctx.run_context,
            contact_data=contact_data,
            channel=channel,
        )
    if isinstance(template, dict):
        return {
            k: _render_body_template(
                v, ctx=ctx, contact_data=contact_data, channel=channel
            )
            for k, v in template.items()
        }
    if isinstance(template, list):
        return [
            _render_body_template(item, ctx=ctx, contact_data=contact_data, channel=channel)
            for item in template
        ]
    return template


def _apply_captures(capture_spec: dict[str, str], json_data: Any) -> dict[str, Any]:
    """Simple ``$.a.b.c`` dot-path extractor. Returns a flat
    ``{alias: value}`` dict; missing paths render as ``None``.

    v1 doesn't support wildcards / filters — a full JSONPath
    library would be a heavier dep than warranted while the surface
    is small."""
    out: dict[str, Any] = {}
    if not isinstance(capture_spec, dict) or json_data is None:
        return out
    for alias, path in capture_spec.items():
        if not isinstance(path, str):
            continue
        cursor: Any = json_data
        segments = path.lstrip("$.").split(".")
        for seg in segments:
            if isinstance(cursor, dict) and seg in cursor:
                cursor = cursor[seg]
            else:
                cursor = None
                break
        out[str(alias)] = cursor
    return out


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` with likely-secret values
    replaced. Used for transcript output — the raw values still get
    sent."""
    redacted: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in {"authorization", "cookie", "x-api-key", "x-auth-token"}:
            redacted[k] = "***redacted***"
        else:
            redacted[k] = v
    return redacted


register_node(_NODE_TYPE, handle)
