"""SQLAlchemy ORM models for FundBot.

This module defines the database schema used by the bot.  It uses the
declarative mapping API provided by SQLAlchemy 2.0.  There are three
entities:

* :class:`User` describes a Telegram user who has interacted with the bot.
* :class:`Campaign` represents a fundraising campaign created by a financier.
* :class:`CampaignMember` associates a user with a campaign and tracks
  whether they have paid their contribution.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, Integer, Boolean, DateTime, ForeignKey, func, UniqueConstraint
from datetime import datetime
from typing import Optional


class Base(DeclarativeBase):
    """Base class for declarative models."""
    pass


class User(Base):
    """A Telegram user who has interacted with the bot.

    Attributes
    ----------
    id : int
        Telegram user identifier.
    username : str | None
        Public username of the user if available.
    full_name : str | None
        Full name provided by the user during registration.  If ``None``
        the user has either not provided a name yet or is the financier.
    is_financier : bool
        ``True`` if the user is designated as a financier (admin).
    created_at : datetime
        Timestamp of when the user record was first created.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Use Optional[str] instead of the "|" union syntax for Python 3.9 compatibility
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_financier: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Campaign(Base):
    """A fundraising campaign announced by a financier.

    When a financier announces a campaign using the ``/new`` command, a
    :class:`Campaign` instance is created and a corresponding
    :class:`CampaignMember` is created for every user who has registered
    prior to the campaign announcement (excluding, by default, the
    announcing financier).  The campaign tracks the total amount being
    collected and the amount expected per participant.
    """

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120))
    total_amount: Mapped[int] = mapped_column(Integer)
    per_user_amount: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CampaignMember(Base):
    """Associates a :class:`User` with a :class:`Campaign`.

    Each participant has a flag indicating whether they have paid their
    contribution and an optional timestamp when they did so.
    """

    __tablename__ = "campaign_members"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    has_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    # Use Optional[datetime] instead of union syntax for Python 3.9 compatibility
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
