"""Handlers for common user commands and registration flow.

This module defines handlers for commands available to all users, such as
``/start`` and ``/status``.  It implements a small finite state machine using
aiogram's FSM context to prompt non-financier users for their surname on first
registration.  The surname is validated against a financier-managed allowlist
(``allowed_names`` table) and must be unique among registered users; it is then
stored in the ``users.full_name`` column.
"""

from __future__ import annotations

import html
import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select

from ..db import Session
from ..repo import upsert_user, user_status, is_name_allowed, is_name_taken, get_setting
from ..config import settings
from ..models import User, PAYMENT_NONE, PAYMENT_CLAIMED, PAYMENT_CONFIRMED


logger = logging.getLogger(__name__)
router = Router()


class RegistrationState(StatesGroup):
    """FSM states for user registration."""
    awaiting_name = State()


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext) -> None:
    """Handle the ``/start`` command.

    The user is inserted or updated in the database.  If they are not a
    financier and have not yet registered a surname, the bot prompts them for
    one and enters the registration state.  Otherwise it sends a greeting.
    """
    async with Session() as db:
        user = await upsert_user(
            db,
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name,
            set(settings.FINANCIERS),
        )

    # Non-financiers must register a surname before using the bot.
    if not user.is_financier and not user.full_name:
        await message.answer(
            "Пожалуйста, введите вашу фамилию, чтобы завершить регистрацию.\n"
            "Она будет видна финансисту."
        )
        await state.set_state(RegistrationState.awaiting_name)
        return

    await message.answer(
        "Привет!\n"
        "Используйте команду /status, чтобы узнать свой статус в активном сборе.\n"
        "Список команд: /help"
    )


@router.message(RegistrationState.awaiting_name)
async def process_name(message: Message, state: FSMContext) -> None:
    """Process the user's reply with their surname."""
    surname = (message.text or "").strip()
    if not surname:
        await message.answer("Пустое имя. Попробуйте ещё раз.")
        return

    async with Session() as db:
        u = await db.scalar(select(User).where(User.id == message.from_user.id))
        if u is None:
            await message.answer("Сначала отправьте /start.")
            await state.clear()
            return
        if not await is_name_allowed(db, surname):
            await message.answer(
                "Такой фамилии нет в списке.\n"
                "Проверьте написание или обратитесь к финансисту."
            )
            return
        if await is_name_taken(db, surname):
            await message.answer(f"Фамилия «{surname}» уже занята.\nПопробуйте ещё раз.")
            return
        u.full_name = surname
        await db.commit()

    await message.answer("Ваша фамилия сохранена. Теперь вы можете пользоваться ботом.")
    await state.clear()


@router.message(Command("status"))
async def status_handler(message: Message) -> None:
    """Show the user's status in the active campaign."""
    async with Session() as db:
        camp, member, user, per_user = await user_status(db, message.from_user.id)

    role = None
    if user is not None:
        role = "финансист" if user.is_financier else "участник"
    role_line = f"Ваш статус: {role.capitalize()}" if role else ""

    if not camp:
        await message.answer("Активного сбора нет.\n" f"{role_line}")
        return
    title = html.escape(camp.title)
    if member is None:
        await message.answer(
            f"Текущий сбор: {title}\n"
            "Вы не входите в список участников текущего сбора.\n"
            f"{role_line}"
        )
        return
    status_text = {
        PAYMENT_CONFIRMED: "оплата подтверждена",
        PAYMENT_CLAIMED: "отмечено, ожидает подтверждения",
    }.get(member.status, "ещё не оплачено")
    requisites_line = ""
    if member.status == PAYMENT_NONE:
        async with Session() as db:
            req = await get_setting(db, "requisites")
        if req:
            requisites_line = f"\nРеквизиты для перевода:\n{html.escape(req)}"
    await message.answer(
        f"Текущий сбор: {title}\n"
        f"Ваша доля: {per_user}₽\n"
        f"Статус оплаты: {status_text}\n"
        f"{role_line}"
        f"{requisites_line}"
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    """Send a list of available commands depending on the user's role."""
    async with Session() as db:
        _, _, user, _ = await user_status(db, message.from_user.id)
    is_financier = bool(user and user.is_financier)
    lines = [
        "<b>Доступные команды:</b>",
        "/start – начать или перезапустить диалог",
        "/status – узнать ваш статус в текущем сборе",
        "/admin_message &lt;текст&gt; – написать финансисту",
        "/help – вывести этот список команд",
    ]
    if is_financier:
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
            "/names – показать список разрешённых фамилий",
            "/addname &lt;фамилия&gt; – добавить фамилию в список",
            "/delname &lt;фамилия&gt; – удалить фамилию из списка",
            "/setrequisites &lt;текст&gt; – задать реквизиты для перевода",
            "/deadline &lt;ДД.ММ.ГГГГ&gt; – установить срок сбора",
            "/history – история сборов",
            "/report – выгрузить Excel-отчёт",
        ])
    await message.answer("\n".join(lines))


@router.message(Command("admin_message"))
async def message_to_admin_handler(message: Message, command: CommandObject) -> None:
    text = (command.args or "").strip()
    if not text:
        await message.answer("Использование: /admin_message <текст сообщения>")
        return

    admin_id = settings.ADMIN_TG_ID
    if admin_id is None:
        await message.answer("Получатель сообщений не настроен. Обратитесь к администратору.")
        logger.warning("admin_message: ADMIN_TG_ID is not configured")
        return

    async with Session() as db:
        u = await db.scalar(select(User).where(User.id == message.from_user.id))
    sender = (u.full_name if u and u.full_name else None) or (
        message.from_user.full_name or str(message.from_user.id)
    )
    await message.bot.send_message(
        admin_id,
        f"Сообщение от пользователя {html.escape(sender)}:\n{html.escape(text)}",
    )
    await message.answer("Финансист получил ваше сообщение ^^")
