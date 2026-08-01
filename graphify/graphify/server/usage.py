"""Recording LLM spend into usage_events.

Call `record_usage(...)` from any path that spends provider tokens
(extraction, agent queries, credential verification). Pricing comes from
graphify/llm.py's registry where available so the recorded cost matches what
the engine actually used, rather than a second hardcoded price table that
would drift.

Recording is best-effort by design: a failure to write a usage row must
never fail the user's actual request. Errors are logged, not raised.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.models import UsageEvent

logger = logging.getLogger("graphify.server.usage")


# The admin UI names Anthropic "anthropic"; llm.py's BACKENDS registry keys
# it "claude" (see routes/admin.py's provider docstring). Map before pricing
# lookup, or every Anthropic call silently costs $0.
_PROVIDER_TO_BACKEND = {"anthropic": "claude"}


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Cost in USD for a call, using llm.py's published per-backend pricing.

    Returns 0 for unknown backends rather than guessing — a visibly missing
    number in a spend report is better than a confidently wrong one.

    Note this prices per *backend*, not per model: llm.py's table carries one
    rate per backend (its default model's), so a non-default model on the same
    backend is approximated. Good enough for a spend dashboard, not for
    invoicing.
    """
    try:
        from graphify.llm import estimate_cost as llm_estimate_cost
    except Exception:  # pragma: no cover - llm.py imports optional extras
        logger.debug("could not import graphify.llm for pricing", exc_info=True)
        return Decimal("0")

    backend = _PROVIDER_TO_BACKEND.get(provider, provider)
    try:
        usd = llm_estimate_cost(backend, prompt_tokens, completion_tokens)
    except Exception:
        logger.debug("pricing lookup failed for backend=%s", backend, exc_info=True)
        return Decimal("0")

    # str() first: Decimal(float) would carry the float's binary error into a
    # column we sum for money.
    return Decimal(str(usd))


async def record_usage(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    operation: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    user_id: UUID | None = None,
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    cost_estimate: Decimal | None = None,
) -> None:
    """Append one usage row. Never raises — see module docstring."""
    try:
        cost = (
            cost_estimate
            if cost_estimate is not None
            else estimate_cost(provider, model, prompt_tokens, completion_tokens)
        )
        db.add(
            UsageEvent(
                user_id=user_id,
                project_id=project_id,
                run_id=run_id,
                provider=provider,
                model=model,
                operation=operation,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_estimate=cost,
            )
        )
        await db.commit()
    except Exception:
        logger.exception("failed to record usage event for provider=%s model=%s", provider, model)
