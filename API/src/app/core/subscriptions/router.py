"""Subscription / plan routes.

Six endpoints live here:

  GET  /api/v1/plans                          — public list (trial excluded)
  GET  /api/v1/plans/{code}                   — single plan, includes trial
  GET  /api/v1/subscriptions/current          — composed read of the
                                                caller's org's subscription
  POST /api/v1/subscriptions/change           — request a plan / cycle /
                                                seat change
  GET  /api/v1/subscriptions/seats/preview    — see the cost impact of a
                                                proposed seat change
  POST /api/v1/subscriptions/seats            — apply or schedule a seat
                                                change

The first two are unauthenticated — the marketing `/pricing` page and
the signup flow consume them before the visitor is logged in. The rest
require auth; cancellation lands in Step 10. The Owner-only RBAC gate
arrives in Step 19 via the `billing.manage` permission key — until
then any authenticated org member can call the write paths.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.subscriptions import plans, service as subscription_service
from src.app.core.subscriptions.dependencies import get_payment_provider
from src.app.core.subscriptions.payment_provider import PaymentProvider
from src.app.core.subscriptions.schemas import (
    CancelSubscriptionResponse,
    CheckoutRequest,
    CheckoutResponse,
    InvoiceRead,
    NeedsPaymentResponse,
    PlanChangeRequest,
    PlanChangeResponse,
    SeatChangeNeedsPaymentResponse,
    SeatChangeRequest,
    SeatChangeResponse,
    SeatPreview,
    SubscriptionCurrentResponse,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


# Hosts the checkout URLs may redirect to. Anything outside this set
# is rejected with 400 to prevent the endpoint from being used as an
# open redirect — Stripe will gladly redirect anywhere the host gives
# it. Localhost ports cover the dev workflow; production deployments
# add their public host via a future config flag (out of scope for v1).
_ALLOWED_REDIRECT_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
    }
)


def _validate_redirect_url(raw: str | None) -> None:
    """Reject off-domain redirects. Empty / `None` is OK — caller defaults it."""
    if not raw:
        return
    from urllib.parse import urlparse

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_redirect", "value": raw},
        )
    host = parsed.hostname or ""
    if host not in _ALLOWED_REDIRECT_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_redirect", "value": raw},
        )


def _default_redirect(request: Request, kind: str) -> str:
    """Origin-aware fallback when the client omits a URL.

    `kind` is `"success"` or `"cancel"`. Both default to the in-app
    billing settings page; the query string distinguishes them so the
    Angular route can swap a toast.
    """
    origin = (
        request.headers.get("origin")
        or f"{request.url.scheme}://{request.url.netloc}"
    )
    suffix = "?upgraded=true" if kind == "success" else ""
    return f"{origin}/user/settings/billing{suffix}"


router = APIRouter(tags=["Subscriptions"])


@router.get("/plans")
async def list_public_plans() -> dict:
    return {
        "plans": [p.serialize() for p in plans.public()],
        "currency": plans.currency(),
        "annual_discount_pct": plans.annual_discount_pct(),
    }


@router.get("/plans/{code}")
async def get_plan(code: str) -> dict:
    plan = plans.get(code)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown plan code: {code!r}",
        )
    return plan.serialize()


@router.get(
    "/subscriptions/current",
    response_model=SubscriptionCurrentResponse,
)
async def get_current_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionCurrentResponse:
    """Return the caller's org's active subscription with plan + usage.

    Read is open to any authenticated user in the org — managing the
    plan / seats / cancellation lives behind the Owner role gate in
    Steps 8-10 (RBAC keys registered in Step 19).
    """
    return await subscription_service.compose_current_subscription_response(
        db, user.org_id
    )


@router.post(
    "/subscriptions/change",
    response_model=PlanChangeResponse,
)
async def change_subscription(
    payload: PlanChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    payment_provider: PaymentProvider | None = Depends(get_payment_provider),
):
    """Request a plan / billing-cycle / seat change for the caller's org.

    Returns one of three discriminated-union shapes — `no_change`,
    `needs_payment`, or `scheduled` — selected by the service. When the
    Stripe provider is configured and the outcome is `needs_payment`,
    the route post-processes the response to attach a real
    `checkout_url`; otherwise `checkout_url` stays `None` and the
    frontend renders the preview only.

    4xx detail bodies use the structured `{"error": "<code>", ...}`
    shape so the frontend can decode them without parsing strings.

    The Owner-only RBAC gate is added in Step 19; for now any
    authenticated org member can call this endpoint. Read-only and
    archived subs DELIBERATELY pass auth here — this is the recovery
    path the trial-ended banner links to.
    """
    result = await subscription_service.change_plan(
        db,
        user.org_id,
        to_plan=payload.to_plan,
        billing_cycle=payload.billing_cycle,
        seats=payload.seats,
    )
    if isinstance(result, NeedsPaymentResponse) and payment_provider is not None:
        result = await subscription_service.attach_checkout_to_needs_payment(
            db,
            user.org_id,
            result,
            success_url=_default_redirect(request, "success"),
            cancel_url=_default_redirect(request, "cancel"),
            user_email=user.email or "",
            user_full_name=user.full_name or "",
            payment_provider=payment_provider,
        )
    return result


@router.get(
    "/subscriptions/seats/preview",
    response_model=SeatPreview,
)
async def preview_seat_change(
    total_seats: int = Query(..., ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SeatPreview:
    """Read-only cost projection for the seat-management modal.

    Does not commit anything; the UI calls this on input change and
    renders `amount_due_usd` + the projected per-cycle cost. The
    commit path (POST) does its own validation and may reject the
    request, so `outcome_if_committed` is informational, not a
    promise.
    """
    return await subscription_service.preview_seat_change(
        db, user.org_id, total_seats
    )


@router.post(
    "/subscriptions/seats",
    response_model=SeatChangeResponse,
)
async def change_seats(
    payload: SeatChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    payment_provider: PaymentProvider | None = Depends(get_payment_provider),
):
    """Apply or schedule a seat-count change.

    `total_seats` is the desired *total*, not a delta. Adding seats
    on a paid plan returns `needs_payment` (this route fills the
    `checkout_url` when the Stripe provider is configured); removing
    seats schedules at the next period boundary; no_change returns
    immediately. Trial subs cannot add seats (use upgrade instead).
    """
    result = await subscription_service.change_seats(
        db, user.org_id, total_seats=payload.total_seats,
    )
    if (
        isinstance(result, SeatChangeNeedsPaymentResponse)
        and payment_provider is not None
    ):
        result = await subscription_service.attach_checkout_to_seats_needs_payment(
            db,
            user.org_id,
            result,
            success_url=_default_redirect(request, "success"),
            cancel_url=_default_redirect(request, "cancel"),
            user_email=user.email or "",
            user_full_name=user.full_name or "",
            payment_provider=payment_provider,
        )
    return result


@router.post(
    "/subscriptions/checkout",
    response_model=CheckoutResponse,
)
async def open_checkout(
    payload: CheckoutRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    payment_provider: PaymentProvider | None = Depends(get_payment_provider),
) -> CheckoutResponse:
    """Direct checkout for the trial-banner / pricing-page upgrade flow.

    Unlike `POST /subscriptions/change`, this endpoint does not
    schedule a state change; it only opens a hosted Checkout session
    for the requested plan + cycle + seats. The webhook in Step 13
    applies the actual subscription change when payment completes.

    Validates the requested plan + seats per the same rules as
    `change_plan` so the user never reaches Stripe with a request the
    server would reject after payment. Rejects off-domain `success_url`
    / `cancel_url` values to close the open-redirect surface.

    Requires the Stripe provider to be configured. If not, returns
    503 — the trial banner shouldn't have shown the Upgrade button in
    that case.
    """
    if payment_provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "payment_provider_unavailable"},
        )
    _validate_redirect_url(payload.success_url)
    _validate_redirect_url(payload.cancel_url)

    success_url = payload.success_url or _default_redirect(request, "success")
    cancel_url = payload.cancel_url or _default_redirect(request, "cancel")

    return await subscription_service.create_direct_checkout(
        db,
        user.org_id,
        to_plan=payload.to_plan,
        billing_cycle=payload.billing_cycle,
        seats=payload.seats,
        success_url=success_url,
        cancel_url=cancel_url,
        user_email=user.email or "",
        user_full_name=user.full_name or "",
        payment_provider=payment_provider,
    )


@router.get(
    "/subscriptions/invoices",
    response_model=list[InvoiceRead],
)
async def list_subscription_invoices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InvoiceRead]:
    """Return the org's Stripe invoices, newest first.

    Populated by Step 13.b's `invoice.*` webhook handlers; rows here
    are the local mirror of Stripe's invoice objects with the
    `hosted_invoice_url` / `pdf_url` links the customer clicks
    through to view the document.

    No pagination — v1 orgs collect at most ~24 invoices a year and
    the billing-settings page renders the list inline. Read access
    is open to any authenticated org member; managing payment is
    Owner-only via Step 19's RBAC.
    """
    return await subscription_service.list_invoices(db, user.org_id)


@router.post(
    "/subscriptions/cancel",
    response_model=CancelSubscriptionResponse,
)
async def cancel_subscription_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CancelSubscriptionResponse:
    """Mark the caller's org subscription cancelled.

    Idempotent — calling twice returns the same `cancelled_at` with
    `already_cancelled=true`. The local row flip is enough to revoke
    write access via the SubscriptionStateMiddleware; the Stripe-side
    sub is cancelled by Step 13's webhook.

    Owner-only RBAC arrives in Step 19 (`billing.manage` permission
    key); for now any authenticated org member can call it. The
    middleware passes this path through even on already-cancelled subs
    so the idempotent contract holds end-to-end.
    """
    return await subscription_service.cancel_subscription(
        db, user.org_id,
    )
