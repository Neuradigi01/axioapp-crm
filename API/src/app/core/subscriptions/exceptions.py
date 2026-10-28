"""Structured 402 used by the entitlement layer.

`EntitlementError` carries a machine-readable `detail` dict so the
frontend (the Upgrade modal in Step 17 and the locked-tile pattern in
Step 18) can pick the right copy without parsing strings.

It inherits from `fastapi.HTTPException`, so FastAPI's default exception
handler produces a JSON response shaped:

    {
      "reason": "feature_locked",
      "required_plan": "standard",
      "resource": null,
      "cap": null,
      "message": "This feature requires the Standard plan or higher."
    }

The legacy `http_exception_handler` in `src/app/main.py` already passes
`dict` details through verbatim, so the structure reaches the client
without being collapsed into `{"success": false, "message": ...}`.
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status

EntitlementReason = Literal[
    "feature_locked",  # plan does not grant the requested feature
    "cap_reached",  # resource counter is at the plan's cap
    "read_only",  # subscription status forbids writes
    "trial_expired",  # convenience alias for read_only when triggered by trial expiry
]


_DEFAULT_MESSAGES: dict[str, str] = {
    "feature_locked": "This feature is not included in your current plan.",
    "cap_reached": "You have reached your plan's limit for this resource.",
    "read_only": "Your subscription is read-only. Upgrade to continue.",
    "trial_expired": "Your trial has ended. Upgrade to continue using the CRM.",
}


class EntitlementError(HTTPException):
    """HTTP 402 Payment Required with a structured `detail` payload."""

    def __init__(
        self,
        reason: EntitlementReason,
        *,
        required_plan: str | None = None,
        resource: str | None = None,
        cap: int | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "reason": reason,
                "required_plan": required_plan,
                "resource": resource,
                "cap": cap,
                "message": message or _DEFAULT_MESSAGES[reason],
            },
        )
        # Stash the structured fields on the instance for tests + log lines —
        # `HTTPException.detail` is already structured but quicker access here.
        self.reason: EntitlementReason = reason
        self.required_plan: str | None = required_plan
        self.resource: str | None = resource
        self.cap: int | None = cap
