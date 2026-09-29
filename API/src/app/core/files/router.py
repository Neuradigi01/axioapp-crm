"""`GET /files/{key}` — public images from the storage backend.

Mounted at the app root (not `/api/v1`) because stored URLs are
`/files/<key>` (see `StorageBackend.url`). No login: `<img>` tags on
the public store, listings and chat widget cannot send a token. What
may be served is decided in `service.open_public_file`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse

from config import TRUSTED_PROXIES
from src.app.core.files.service import open_public_file
from src.app.shared.http.client_ip import parse_client_ip, parse_trusted_proxies
from src.app.shared.rate_limit import InMemoryRateLimiter

router = APIRouter(tags=["files"])

# A store page with a full product grid loads a few dozen images per
# view (each revalidated with If-None-Match); 600/min per IP leaves
# plenty of headroom while stopping key-guessing floods.
_limiter = InMemoryRateLimiter(max_hits=600, window_seconds=60.0)
_trusted_proxies = parse_trusted_proxies(TRUSTED_PROXIES)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    # Keys like `cover.jpg` are overwritten in place on replace, so the
    # browser must revalidate every time (cheap: 304 on a match).
    "Cache-Control": "no-cache",
}


@router.get("/files/{key:path}")
async def get_public_file(key: str, request: Request) -> Response:
    result = _limiter.check(f"files:{parse_client_ip(request, _trusted_proxies)}")
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Try again shortly.",
            headers={"Retry-After": str(int(result.retry_after) + 1)},
        )

    public_file = await open_public_file(key, if_none_match=request.headers.get("if-none-match"))
    headers = {**_SECURITY_HEADERS, "ETag": public_file.etag}
    if public_file.body is None:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return StreamingResponse(
        public_file.body,
        media_type=public_file.content_type,
        headers={**headers, "Content-Length": str(public_file.size)},
    )
