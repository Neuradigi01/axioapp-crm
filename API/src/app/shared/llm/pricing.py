"""USD-per-1K-tokens pricing table.

Hardcoded because provider pricing changes are a *deliberate*
config update, not a runtime concern. When OpenAI drops prices or
adds a new model, this file gets a bump.

Cost calculation is always **server-side** — computed from the
:class:`~src.app.shared.llm.base.Usage` values returned by the
provider itself, never from client-reported numbers (Attacker M7:
"Cost is always computed server-side from OpenAI's ``usage`` field
on the completion response. Never accept usage from the widget.").
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.app.shared.llm.base import Usage


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """USD per 1000 tokens. Set ``completion`` to ``None`` for
    embedding-only models (there's no completion component)."""

    prompt: Decimal
    completion: Decimal | None


# Prices sourced from https://openai.com/api/pricing/ as of 2026-08-19.
# Bump when a price change ships. Missing model → raises KeyError at
# ``cost_for`` time, which surfaces as a runtime error, which is the
# right default (silently mis-billing is worse).
_PRICES: dict[str, ModelPricing] = {
    # Chat models.
    "gpt-4o": ModelPricing(
        prompt=Decimal("0.0025"),
        completion=Decimal("0.01"),
    ),
    "gpt-4o-mini": ModelPricing(
        prompt=Decimal("0.00015"),
        completion=Decimal("0.0006"),
    ),
    "gpt-4-turbo": ModelPricing(
        prompt=Decimal("0.01"),
        completion=Decimal("0.03"),
    ),
    "gpt-3.5-turbo": ModelPricing(
        prompt=Decimal("0.0005"),
        completion=Decimal("0.0015"),
    ),
    # Embedding models — completion component is None.
    "text-embedding-3-small": ModelPricing(
        prompt=Decimal("0.00002"),
        completion=None,
    ),
    "text-embedding-3-large": ModelPricing(
        prompt=Decimal("0.00013"),
        completion=None,
    ),
}


def cost_for(usage: Usage, model: str) -> Decimal:
    """Return the USD cost for a completion or embedding call.

    Prompt-tokens billed at ``price.prompt``; completion-tokens at
    ``price.completion``. For embedding models the completion
    component is None and completion_tokens is ignored.

    Result is a :class:`Decimal` so caller can store it in
    ``tbl_ai_assistant_message_meta.cost_usd`` without a
    ``float``→``Numeric`` round-trip loss.
    """
    if model not in _PRICES:
        raise KeyError(
            f"no pricing entry for model={model!r}. "
            "Add it to src/app/shared/llm/pricing.py."
        )
    price = _PRICES[model]
    prompt_cost = (Decimal(usage.prompt_tokens) / Decimal(1000)) * price.prompt
    if price.completion is None:
        return prompt_cost
    completion_cost = (Decimal(usage.completion_tokens) / Decimal(1000)) * price.completion
    return prompt_cost + completion_cost


def known_models() -> list[str]:
    """Enumerate the models the pricing table knows about — used by
    the Instructions-tab model dropdown (Step 8) so the UI never
    lets an operator pick a model we can't cost."""
    return list(_PRICES.keys())


__all__ = ["ModelPricing", "cost_for", "known_models"]
