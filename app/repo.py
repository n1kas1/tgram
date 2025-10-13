"""Repository layer for database access.

This module encapsulates all interactions with the database so that the
handlers remain focused on chat logic.  If you wish to switch to a
different database toolkit (for example, using raw asyncpg instead of
SQLAlchemy), you can do so by re-implementing the functions in this module
without changing the rest of the codebase.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Tuple, Optional, List

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User, Campaign, CampaignMember


async def upsert_user(db: AsyncSession, tg_id: int, username: Optional[str], full_name: Optional[str], financiers: set[int]) -> User:
    """Insert or update a user record.

    If the user does not already exist in the database, a new record is
    created.  Existing users have their username updated.  The
    ``full_name`` is only set if it is not already present; this prevents
    overwriting a name the user has provided via the registration flow.  The
    ``is_financier`` flag is set if the Telegram ID appears in the provided
    ``financiers`` set.
    """
    u = await db.scalar(select(User).where(User.id == tg_id))
    if u is None:
        u = User(id=tg_id, username=username, full_name=full_name, is_financier=(tg_id in financiers))
        db.add(u)
    else:
        u.username = username
        # only set full_name if we have a new value and the old value is empty
        if full_name and not u.full_name:
            u.full_name = full_name
        # don't downgrade a financier if already true
        if tg_id in financiers:
            u.is_financier = True
    await db.commit()
    return u


async def get_all_users(db: AsyncSession) -> list[User]:
    """Return a list of all users sorted by their creation timestamp."""
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars())


async def list_user_ids(db: AsyncSession) -> list[int]:
    """Return a list of all user Telegram IDs."""
    res = await db.execute(select(User.id).order_by(User.id))
    return [row[0] for row in res.all()]


async def create_campaign(db: AsyncSession, title: str, total_amount: int, creator_id: int) -> Tuple[Campaign, List[int], int]:
    """Create a new campaign.

    The current list of users is captured at creation time (excluding the
    financier who initiates the campaign).  A :class:`CampaignMember` row is
    created for each participant.  The per-user share of the total is
    calculated using a ceiling division so that the total is fully covered.

    Returns a tuple containing the new :class:`Campaign`, the list of user
    IDs included in the campaign, and the per-user amount.
    """
    user_ids = await list_user_ids(db)
    # Exclude the creator from paying unless you want to include them; comment
    # out the line below to include the financier.
    user_ids = [uid for uid in user_ids if uid != creator_id]
    n = max(len(user_ids), 1)
    per_user = (total_amount + n - 1) // n  # ceiling division
    camp = Campaign(title=title, total_amount=total_amount, per_user_amount=per_user, created_by=creator_id)
    db.add(camp)
    await db.flush()  # assign campaign ID
    for uid in user_ids:
        db.add(CampaignMember(campaign_id=camp.id, user_id=uid))
    await db.commit()
    return camp, user_ids, per_user


async def toggle_payment(db: AsyncSession, campaign_id: int, user_id: int, mark: bool) -> bool:
    """Mark or unmark a payment for a user within a campaign.

    Returns ``True`` if the campaign member existed and the flag was updated.
    """
    cm = await db.scalar(select(CampaignMember).where(
        CampaignMember.campaign_id == campaign_id, CampaignMember.user_id == user_id
    ))
    if not cm:
        return False
    cm.has_paid = mark
    cm.paid_at = datetime.now(timezone.utc) if mark else None
    await db.commit()
    return True


async def campaign_stats(db: AsyncSession, campaign_id: int) -> Tuple[int, int, int]:
    """Return (total_participants, paid_count, unpaid_count) for a campaign."""
    total = await db.scalar(select(func.count(CampaignMember.id)).where(CampaignMember.campaign_id == campaign_id))
    paid = await db.scalar(select(func.count(CampaignMember.id)).where(
        CampaignMember.campaign_id == campaign_id,
        CampaignMember.has_paid == True,
    ))
    unpaid = total - paid
    return total, paid, unpaid


async def list_paid_unpaid(db: AsyncSession, campaign_id: int) -> Tuple[list[int], list[int]]:
    """Return two lists of user IDs: those who have paid and those who have not."""
    res = await db.execute(select(CampaignMember.user_id, CampaignMember.has_paid).where(
        CampaignMember.campaign_id == campaign_id
    ))
    paid: list[int] = []
    unpaid: list[int] = []
    for uid, ok in res.all():
        (paid if ok else unpaid).append(uid)
    return paid, unpaid


async def get_active_campaign(db: AsyncSession) -> Optional[Campaign]:
    """Return the most recently created active campaign, or ``None``."""
    return await db.scalar(select(Campaign).where(Campaign.is_active == True).order_by(Campaign.id.desc()))


async def close_active_campaign(db: AsyncSession) -> bool:
    """Close the current active campaign.

    Returns ``True`` if a campaign was closed, ``False`` if there was no
    active campaign.
    """
    camp = await get_active_campaign(db)
    if not camp:
        return False
    camp.is_active = False
    await db.commit()
    return True


async def user_status(db: AsyncSession, user_id: int) -> Tuple[Optional[Campaign], Optional[CampaignMember], Optional[User], Optional[int]]:
    """Return the user's status in the active campaign.

    Returns a tuple ``(campaign, member, user, per_user_amount)``.  If no
    active campaign exists or the user is not part of it, the campaign and
    member will be ``None``.
    """
    camp = await get_active_campaign(db)
    if not camp:
        return None, None, None, None
    cm = await db.scalar(select(CampaignMember).where(
        CampaignMember.campaign_id == camp.id,
        CampaignMember.user_id == user_id
    ))
    user = await db.scalar(select(User).where(User.id == user_id))
    return camp, cm, user, camp.per_user_amount if cm else None


async def get_user(db: AsyncSession, user_id: int) -> Optional[User]:
    """Return a User instance for the given Telegram ID, or None if not found."""
    return await db.scalar(select(User).where(User.id == user_id))
