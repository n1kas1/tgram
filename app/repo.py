"""Repository layer for database access.

This module encapsulates all interactions with the database so that the
handlers remain focused on chat logic.  If you wish to switch to a
different database toolkit (for example, using raw asyncpg instead of
SQLAlchemy), you can do so by re-implementing the functions in this module
without changing the rest of the codebase.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple, Optional, List

from sqlalchemy import select, func, delete, cast, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    User,
    Campaign,
    CampaignMember,
    AllowedName,
    Setting,
    PAYMENT_NONE,
    PAYMENT_CLAIMED,
    PAYMENT_CONFIRMED,
)


async def upsert_user(db: AsyncSession, tg_id: int, username: Optional[str], tg_name: Optional[str], financiers: set[int]) -> User:
    """Insert or update a user record.

    If the user does not already exist, a new record is created.  ``username``
    and the Telegram display name (``tg_name``) are kept in sync on every call.
    The ``full_name`` (the surname the participant registers with) is never
    touched here — it is set only via the registration flow.  The
    ``is_financier`` flag is set if the Telegram ID appears in ``financiers``.
    """
    u = await db.scalar(select(User).where(User.id == tg_id))
    if u is None:
        u = User(id=tg_id, username=username, tg_name=tg_name, is_financier=(tg_id in financiers))
        db.add(u)
    else:
        u.username = username
        u.tg_name = tg_name
        # don't downgrade a financier if already true
        if tg_id in financiers:
            u.is_financier = True
    await db.commit()
    return u


async def is_name_allowed(db: AsyncSession, name: str) -> bool:
    """Return True if ``name`` is in the financier-managed allowlist."""
    found = await db.scalar(select(AllowedName.id).where(AllowedName.name == name))
    return found is not None


async def is_name_taken(db: AsyncSession, name: str) -> bool:
    """Return True if another user has already registered with ``name``."""
    found = await db.scalar(select(User.id).where(User.full_name == name))
    return found is not None


async def add_allowed_name(db: AsyncSession, name: str) -> bool:
    """Add a surname to the allowlist. Returns False if it already exists."""
    if await is_name_allowed(db, name):
        return False
    db.add(AllowedName(name=name))
    await db.commit()
    return True


async def remove_allowed_name(db: AsyncSession, name: str) -> bool:
    """Remove a surname from the allowlist. Returns False if it was absent."""
    if not await is_name_allowed(db, name):
        return False
    await db.execute(delete(AllowedName).where(AllowedName.name == name))
    await db.commit()
    return True


async def list_allowed_names(db: AsyncSession) -> list[str]:
    """Return all allowed surnames sorted alphabetically."""
    res = await db.execute(select(AllowedName.name).order_by(AllowedName.name))
    return [row[0] for row in res.all()]


async def seed_allowed_names(db: AsyncSession, names: list[str]) -> int:
    """Seed the allowlist with ``names`` if it is currently empty.

    Returns the number of names inserted (0 if the table already had data).
    """
    existing = await db.scalar(select(func.count(AllowedName.id)))
    if existing:
        return 0
    for name in names:
        db.add(AllowedName(name=name))
    await db.commit()
    return len(names)


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


async def _get_member(db: AsyncSession, campaign_id: int, user_id: int) -> Optional[CampaignMember]:
    return await db.scalar(select(CampaignMember).where(
        CampaignMember.campaign_id == campaign_id, CampaignMember.user_id == user_id
    ))


async def claim_payment(db: AsyncSession, campaign_id: int, user_id: int) -> bool:
    """Participant marks that they have paid (status -> claimed).

    Has no effect if the payment was already confirmed by a financier.
    Returns ``True`` if the member exists and is now (or was already) claimed.
    """
    cm = await _get_member(db, campaign_id, user_id)
    if not cm:
        return False
    if cm.status == PAYMENT_CONFIRMED:
        return False
    cm.status = PAYMENT_CLAIMED
    cm.claimed_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def unclaim_payment(db: AsyncSession, campaign_id: int, user_id: int) -> bool:
    """Participant undoes their claim (claimed -> none).

    Has no effect once a financier has confirmed the payment.
    """
    cm = await _get_member(db, campaign_id, user_id)
    if not cm or cm.status == PAYMENT_CONFIRMED:
        return False
    cm.status = PAYMENT_NONE
    cm.claimed_at = None
    await db.commit()
    return True


async def confirm_payment(db: AsyncSession, campaign_id: int, user_id: int) -> bool:
    """Financier confirms receipt (-> confirmed)."""
    cm = await _get_member(db, campaign_id, user_id)
    if not cm:
        return False
    cm.status = PAYMENT_CONFIRMED
    cm.confirmed_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def member_status(db: AsyncSession, campaign_id: int, user_id: int) -> Optional[str]:
    """Return the payment status string for a member, or None if absent."""
    cm = await _get_member(db, campaign_id, user_id)
    return cm.status if cm else None


async def campaign_stats(db: AsyncSession, campaign_id: int) -> Tuple[int, int, int, int]:
    """Return (total, confirmed, claimed, unpaid) counts for a campaign."""
    async def count(*conds) -> int:
        return await db.scalar(
            select(func.count(CampaignMember.id)).where(
                CampaignMember.campaign_id == campaign_id, *conds
            )
        ) or 0

    total = await count()
    confirmed = await count(CampaignMember.status == PAYMENT_CONFIRMED)
    claimed = await count(CampaignMember.status == PAYMENT_CLAIMED)
    unpaid = total - confirmed - claimed
    return total, confirmed, claimed, unpaid


async def list_by_status(db: AsyncSession, campaign_id: int) -> Tuple[list[int], list[int], list[int]]:
    """Return (confirmed_ids, claimed_ids, unpaid_ids) for a campaign."""
    res = await db.execute(select(CampaignMember.user_id, CampaignMember.status).where(
        CampaignMember.campaign_id == campaign_id
    ))
    confirmed: list[int] = []
    claimed: list[int] = []
    unpaid: list[int] = []
    for uid, status in res.all():
        if status == PAYMENT_CONFIRMED:
            confirmed.append(uid)
        elif status == PAYMENT_CLAIMED:
            claimed.append(uid)
        else:
            unpaid.append(uid)
    return confirmed, claimed, unpaid


async def list_outstanding(db: AsyncSession, campaign_id: int) -> list[int]:
    """Return user IDs whose payment is not yet confirmed (none + claimed)."""
    res = await db.execute(select(CampaignMember.user_id).where(
        CampaignMember.campaign_id == campaign_id,
        CampaignMember.status != PAYMENT_CONFIRMED,
    ))
    return [row[0] for row in res.all()]


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


# ---------------------------------------------------------------------------
# Settings (key/value)


async def get_setting(db: AsyncSession, key: str) -> Optional[str]:
    """Return the stored value for ``key`` or None."""
    return await db.scalar(select(Setting.value).where(Setting.key == key))


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    """Insert or update a setting value."""
    s = await db.scalar(select(Setting).where(Setting.key == key))
    if s is None:
        db.add(Setting(key=key, value=value))
    else:
        s.value = value
    await db.commit()


# ---------------------------------------------------------------------------
# Deadline / reminders


async def set_campaign_due_date(db: AsyncSession, campaign_id: int, due_date: Optional[datetime]) -> None:
    """Set (or clear) the deadline of a campaign."""
    camp = await db.scalar(select(Campaign).where(Campaign.id == campaign_id))
    if camp:
        camp.due_date = due_date
        await db.commit()


async def mark_reminded(db: AsyncSession, campaign_id: int) -> None:
    """Record that an auto-reminder was just sent for a campaign."""
    camp = await db.scalar(select(Campaign).where(Campaign.id == campaign_id))
    if camp:
        camp.last_reminded_at = datetime.now(timezone.utc)
        await db.commit()


# ---------------------------------------------------------------------------
# History / reporting


async def list_campaigns(db: AsyncSession, limit: Optional[int] = None) -> list[Campaign]:
    """Return campaigns, newest first."""
    stmt = select(Campaign).order_by(Campaign.id.desc())
    if limit:
        stmt = stmt.limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars())


async def collected_amount(db: AsyncSession, campaign: Campaign) -> int:
    """Return the confirmed amount collected so far for a campaign."""
    confirmed = await db.scalar(
        select(func.count(CampaignMember.id)).where(
            CampaignMember.campaign_id == campaign.id,
            CampaignMember.status == PAYMENT_CONFIRMED,
        )
    ) or 0
    return confirmed * campaign.per_user_amount


async def user_payment_history(db: AsyncSession) -> list[Tuple[int, int, int]]:
    """Aggregate participation per user across all campaigns.

    Returns rows of ``(user_id, campaigns_count, confirmed_count)``.
    """
    res = await db.execute(
        select(
            CampaignMember.user_id,
            func.count(CampaignMember.id),
            func.sum(
                cast(CampaignMember.status == PAYMENT_CONFIRMED, Integer)
            ),
        ).group_by(CampaignMember.user_id)
    )
    out: list[Tuple[int, int, int]] = []
    for uid, total, confirmed in res.all():
        out.append((uid, int(total or 0), int(confirmed or 0)))
    return out
