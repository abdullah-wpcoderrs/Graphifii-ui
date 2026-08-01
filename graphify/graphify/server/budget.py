"""Per-user daily spend cap for agent LLM calls.

The cap is a platform setting an admin edits (stored in app_settings, not in
the environment) so it can be changed without a redeploy. It is enforced
*before* each agent call by summing today's agent usage_events for that
user — the same rows the admin spend dashboard reads, so what the cap
measures and what the dashboard reports can never disagree.

Two deliberate choices worth knowing before changing this:

  * Only operation="agent" counts. Extraction and credential-verify spend is
    platform-initiated, not something a user chose to trigger, so charging
    it against their interactive budget would let a big repo silently
    consume someone's ability to ask questions.

  * The check is pre-call and approximate. A call's real cost is unknown
    until it returns, so a user sitting just under the cap can overshoot it
    by one call. Reserving an estimate up front would fix that at the cost
    of refunding on every failure; for a spend guardrail (not billing) the
    simpler rule is the right trade. Overshoot is bounded by one call.

"Today" is UTC, matching usage_events.created_at, so the window does not
shift with the viewer's timezone.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.models import AppSetting, UsageEvent

logger = logging.getLogger("graphify.server.budget")

AGENT_DAILY_BUDGET_KEY = "agent_daily_budget_usd"

# Applied when an admin has never set the cap. A real number rather than
# "unlimited": an un-configured deployment should fail safe, not hand every
# user an unbounded spend allowance.
DEFAULT_AGENT_DAILY_BUDGET = Decimal("5.00")

# Sentinel an admin can store to turn the cap off entirely.
UNLIMITED = Decimal("-1")


class BudgetExceededError(Exception):
    """Raised when a user has already spent their daily agent allowance."""

    def __init__(self, spent: Decimal, limit: Decimal) -> None:
        self.spent = spent
        self.limit = limit
        super().__init__(
            f"Daily AI budget reached (${spent:.2f} of ${limit:.2f} used). "
            "It resets at 00:00 UTC, or an administrator can raise the limit."
        )


async def get_daily_budget(db: AsyncSession) -> Decimal:
    """The configured per-user daily cap in USD, or UNLIMITED."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == AGENT_DAILY_BUDGET_KEY))
    setting = result.scalar_one_or_none()
    if setting is None:
        return DEFAULT_AGENT_DAILY_BUDGET

    try:
        return Decimal(setting.value)
    except (InvalidOperation, ValueError):
        # A malformed stored value must not read as "unlimited" — fall back
        # to the safe default and make the bad row visible in the log.
        logger.warning(
            "app_settings.%s holds an unparseable value %r; using the default cap",
            AGENT_DAILY_BUDGET_KEY,
            setting.value,
        )
        return DEFAULT_AGENT_DAILY_BUDGET


async def set_daily_budget(db: AsyncSession, limit: Decimal) -> None:
    """Store the per-user daily cap. Pass UNLIMITED to disable enforcement."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == AGENT_DAILY_BUDGET_KEY))
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = AppSetting(key=AGENT_DAILY_BUDGET_KEY, value=str(limit))
        db.add(setting)
    else:
        setting.value = str(limit)
    await db.commit()


async def spent_today(db: AsyncSession, user_id: UUID) -> Decimal:
    """Sum of this user's agent spend since 00:00 UTC."""
    midnight = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)

    result = await db.execute(
        select(func.coalesce(func.sum(UsageEvent.cost_estimate), 0)).where(
            UsageEvent.user_id == user_id,
            UsageEvent.operation == "agent",
            UsageEvent.created_at >= midnight,
        )
    )
    return Decimal(str(result.scalar_one() or 0))


async def check_budget(db: AsyncSession, user_id: UUID) -> tuple[Decimal, Decimal]:
    """Raise BudgetExceededError if this user is out of allowance for today.

    Returns (spent, limit) on success so a caller can surface the remaining
    allowance without querying twice.
    """
    limit = await get_daily_budget(db)
    spent = await spent_today(db, user_id)

    if limit == UNLIMITED:
        return spent, limit
    if spent >= limit:
        raise BudgetExceededError(spent, limit)
    return spent, limit
