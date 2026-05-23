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
    # Display name taken from the Telegram profile (informational only).
    tg_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Surname entered by the participant during registration; stays NULL until
    # the user completes the registration flow.
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
    # Optional payment deadline and the moment the last auto-reminder went out.
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reminded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Payment lifecycle for a campaign member.
PAYMENT_NONE = "none"          # has not claimed payment yet
PAYMENT_CLAIMED = "claimed"    # participant says they paid; awaiting confirmation
PAYMENT_CONFIRMED = "confirmed"  # financier confirmed receipt


class CampaignMember(Base):
    """Associates a :class:`User` with a :class:`Campaign`.

    ``status`` follows the lifecycle none -> claimed -> confirmed.  The
    participant moves it to ``claimed`` ("I paid") and a financier confirms
    actual receipt, moving it to ``confirmed``.
    """

    __tablename__ = "campaign_members"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default=PAYMENT_NONE, server_default=PAYMENT_NONE)
    # Use Optional[datetime] instead of union syntax for Python 3.9 compatibility
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AllowedName(Base):
    """A surname that participants are allowed to register with.

    The list is managed by financiers at runtime (``/addname`` / ``/delname``)
    so that onboarding a new colleague does not require a code change.
    """

    __tablename__ = "allowed_names"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setting(Base):
    """Simple key/value store for runtime-configurable settings.

    Used for values a financier can change without a redeploy, such as the
    payment requisites shown to participants.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(2048))
