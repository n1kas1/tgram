"""Handlers for common user commands and registration flow.

This module defines handlers for commands available to all users, such as
``/start`` and ``/status``.  It also implements a simple finite state
machine using aiogram's FSM context to prompt users for their full name on
first registration (except for financiers).  The collected name is stored
in the ``users.full_name`` column.
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select

from ..db import Session
from ..repo import upsert_user, user_status
from ..config import settings
from ..models import User


router = Router()


class RegistrationState(StatesGroup):
    """FSM states for user registration."""
    awaiting_name = State()


@router.message(F.text == "/start")
async def start_handler(message: Message, state: FSMContext) -> None:
    """Handle the ``/start`` command.

    Upon receiving ``/start``, the bot inserts or updates the user in the
    database.  If the user is not a financier and has not provided a full
    name yet, the bot prompts them to supply one and sets the FSM state
    accordingly.  Otherwise, a standard greeting is sent.
    """
    # Upsert the user, recording their username and full name if present.
    async with Session() as db:
        user = await upsert_user(
            db,
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name,
            set(settings.FINANCIERS),
        )

    # If the user is not a financier and has no recorded name, prompt for one.
    if not user.is_financier and not user.full_name:
        await message.answer(
            "Пожалуйста, введите ваше имя, чтобы завершить регистрацию.\n"
            "Это имя будет видно финансисту."
        )
        await state.set_state(RegistrationState.awaiting_name)
        return

    # Otherwise, send a greeting and basic instructions.
    await message.answer(
        "Привет!\n"
        "Используйте команду /status, чтобы узнать свой статус в активном сборе.\n"
        "Список команд: /help"
    )


@router.message(RegistrationState.awaiting_name)
async def process_name(message: Message, state: FSMContext) -> None:
    """Process the user's reply with their full name."""
    full_name = message.text.strip()
    # Update the user record with the provided name
    async with Session() as db:
        u = await db.scalar(select(User).where(User.id == message.from_user.id))
        if u:
            u.full_name = full_name
            await db.commit()
    await message.answer("Спасибо! Ваше имя сохранено. Теперь вы можете пользоваться ботом.")
    await state.clear()


@router.message(F.text == "/status")
async def status_handler(message: Message) -> None:
    """Show the user's status in the active campaign."""
    async with Session() as db:
        camp, member, user, per_user = await user_status(db, message.from_user.id)

    # Determine the user's role (financier or participant)
    role = None
    if user is not None:
        role = "финансист" if user.is_financier else "участник"
    role_line = f"Ваш статус: {role.capitalize()}" if role else ""

    # No active campaign
    if not camp:
        await message.answer(
            "Активного сбора нет.\n"
            f"{role_line}"
        )
        return
    # User is not part of the campaign
    if member is None:
        await message.answer(
            f"Текущий сбор: {camp.title}\n"
            f"Вы не входите в список участников текущего сбора.\n"
            f"{role_line}"
        )
        return
    # User participates in the campaign
    status_text = "оплачено" if member.has_paid else "ещё не оплачено"
    await message.answer(
        f"Текущий сбор: {camp.title}\n"
        f"Ваша доля: {per_user}₽\n"
        f"Статус оплаты: {status_text}\n"
        f"{role_line}"
    )


# ---------------------------------------------------------------------------
# Help command

@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    """Send a list of available commands depending on the user's role."""
    # Determine if the user is a financier
    async with Session() as db:
        _, _, user, _ = await user_status(db, message.from_user.id)
    is_financier = bool(user and user.is_financier)
    # Base commands available to all users
    lines = [
        "<b>Доступные команды:</b>",
        "/start – начать или перезапустить диалог", 
        "/status – узнать ваш статус в текущем сборе",
        "/help – вывести этот список команд",
    ]
    if is_financier:
        # Additional commands for financiers
        lines.extend([
            "\n<b>Команды финансиста:</b>",
            "/new &lt;сумма&gt; &lt;название&gt; – создать новый сбор",
            "/dash – посмотреть сводку по текущему сбору",
            "/close – закрыть текущий сбор",
            "/csv – экспортировать CSV участников текущего сбора",
            "/users – список всех зарегистрированных пользователей",
            "/unpaid – экспортировать CSV тех, кто не оплатил",
            "/remind – отправить напоминание тем, кто не оплатил",
            "/message &lt;текст&gt; – отправить рассылку всем пользователям",
        ])
    await message.answer("\n".join(lines), parse_mode="HTML")
