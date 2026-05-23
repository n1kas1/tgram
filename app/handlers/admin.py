from __future__ import annotations

"""
Handlers for financier-only commands.

This module contains commands restricted to users designated as financiers.
Financiers can create and manage fundraising campaigns, inspect participant
lists, export CSV reports, manage the surname allowlist, and close campaigns.
"""

import csv
import html
import os
import tempfile
from datetime import datetime
from typing import List

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, FSInputFile

from ..config import settings
from ..db import Session
from ..repo import (
    create_campaign,
    campaign_stats,
    list_paid_unpaid,
    get_active_campaign,
    close_active_campaign,
    get_all_users,
    add_allowed_name,
    remove_allowed_name,
    list_allowed_names,
)
from ..keyboards import payment_kb
from ..models import User
from ..utils import broadcast


router = Router()


def is_financier(user_id: int) -> bool:
    """Return True if the given user ID has financier privileges."""
    return user_id in set(settings.FINANCIERS)


@router.message(Command("new"))
async def new_campaign_handler(message: Message, command: CommandObject) -> None:
    """
    Create a new fundraising campaign.

    Usage:
        /new <amount> <title>

    ``amount`` is the total number of rubles to collect; ``title`` may contain
    spaces.  All registered users (except the financier) receive a notification
    with a button to mark their payment.
    """
    if not is_financier(message.from_user.id):
        await message.answer("Только финансист может создавать сбор.")
        return
    args = (command.args or "").strip()
    if not args:
        await message.answer("Использование: /new <сумма_в_руб> <название>")
        return
    parts = args.split(" ", 1)
    try:
        total = int(parts[0])
    except ValueError:
        await message.answer("Сумма должна быть числом. Пример: /new 50000 Сбор на октябрь")
        return
    if total <= 0:
        await message.answer("Сумма должна быть положительной.")
        return
    title = parts[1].strip().strip('"') if len(parts) > 1 else f"Сбор #{datetime.now().strftime('%Y-%m-%d')}"

    async with Session() as db:
        active = await get_active_campaign(db)
        if active:
            await message.answer(
                f"Уже есть активный сбор «{html.escape(active.title)}».\n"
                "Сначала закройте его командой /close."
            )
            return
        camp, users_ids, per_user = await create_campaign(db, title, total, message.from_user.id)

    safe_title = html.escape(camp.title)
    await message.answer(
        f"Создан сбор <b>{safe_title}</b> на сумму {camp.total_amount}₽.\n"
        f"Участников: {len(users_ids)}. На каждого: {per_user}₽.\n"
        "Рассылаю уведомления...",
    )

    sent = await broadcast(
        message.bot,
        users_ids,
        f"📢 Новый сбор: <b>{safe_title}</b>.\n"
        f"Сколько нужно перевести: {per_user}₽.\n"
        "Пожалуйста, нажмите кнопку, когда переведёте сумму.",
        reply_markup=payment_kb(camp.id, False),
    )
    await message.answer(f"Уведомления отправлены: {sent}/{len(users_ids)}")


@router.message(Command("dash"))
async def dashboard_handler(message: Message) -> None:
    """Display statistics and lists for the active campaign."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        camp = await get_active_campaign(db)
        if not camp:
            await message.answer("Активного сбора нет.")
            return
        total, paid_count, unpaid_count = await campaign_stats(db, camp.id)
        paid_ids, unpaid_ids = await list_paid_unpaid(db, camp.id)
        all_users = await get_all_users(db)
        user_map = {u.id: u for u in all_users}

    remain = max(0, camp.total_amount - paid_count * camp.per_user_amount)
    summary = (
        f"📊 Сбор: <b>{html.escape(camp.title)}</b> ({camp.total_amount}₽)\n"
        f"Участников: {total}\n"
        f"Оплатили: {paid_count}\n"
        f"Не оплатили: {unpaid_count}\n"
        f"Осталось собрать ≈ {remain}₽"
    )
    await message.answer(summary)

    def fmt(uid: int) -> str:
        u = user_map.get(uid)
        name = (u.full_name or u.username or str(uid)) if u else str(uid)
        return f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'

    async def send_list(title: str, ids: List[int]) -> None:
        if not ids:
            await message.answer(f"{title}: нет пользователей.")
            return
        lines = [fmt(i) for i in ids]
        chunk_size = 50
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i : i + chunk_size]
            await message.answer(f"{title}:\n" + "\n".join(chunk))

    await send_list("Оплатили", paid_ids)
    await send_list("Не оплатили", unpaid_ids)


@router.message(Command("close"))
async def close_handler(message: Message) -> None:
    """Close the active campaign."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        ok = await close_active_campaign(db)
    await message.answer("Текущий сбор закрыт." if ok else "Активного сбора нет.")


async def _send_csv(message: Message, rows: list[dict], fieldnames: list[str], prefix: str, caption: str) -> None:
    """Write ``rows`` to a temporary CSV, send it, then remove the file."""
    fd, tmp_path = tempfile.mkstemp(prefix=prefix, suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        await message.answer_document(FSInputFile(tmp_path), caption=caption)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@router.message(Command("csv"))
async def export_csv_handler(message: Message) -> None:
    """Export the participant list of the active campaign as a CSV file."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        camp = await get_active_campaign(db)
        if not camp:
            await message.answer("Активного сбора нет.")
            return
        all_users = await get_all_users(db)
        user_map = {u.id: u for u in all_users}
        paid_ids, unpaid_ids = await list_paid_unpaid(db, camp.id)
    paid_set = set(paid_ids)
    rows = []
    for uid in paid_ids + unpaid_ids:
        user = user_map.get(uid)
        rows.append({
            "Имя": user.full_name if user else "",
            "Оплачено": "да" if uid in paid_set else "нет",
        })
    await _send_csv(
        message, rows, ["Имя", "Оплачено"], "fundbot_", f"Участники сбора {camp.title}"
    )


@router.message(Command("users"))
async def list_users_handler(message: Message) -> None:
    """List all registered users with links to their Telegram accounts."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        users = await get_all_users(db)
    financiers = [u for u in users if u.is_financier]
    participants = [u for u in users if not u.is_financier]

    def fmt_user(u: User, idx: int) -> str:
        name = u.full_name or u.username or str(u.id)
        role = "финансист" if u.is_financier else "участник"
        return f'{idx}. <a href="tg://user?id={u.id}">{html.escape(name)}</a> – {role}'

    lines: List[str] = []
    idx = 1
    for u in financiers + participants:
        lines.append(fmt_user(u, idx))
        idx += 1
    chunk_size = 40
    for i in range(0, len(lines), chunk_size):
        chunk = lines[i : i + chunk_size]
        await message.answer("\n".join(chunk))


@router.message(Command("unpaid"))
async def export_unpaid_handler(message: Message) -> None:
    """Export the list of users who have not paid as a CSV file."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        camp = await get_active_campaign(db)
        if not camp:
            await message.answer("Активного сбора нет.")
            return
        all_users = await get_all_users(db)
        user_map = {u.id: u for u in all_users}
        _, unpaid_ids = await list_paid_unpaid(db, camp.id)
    if not unpaid_ids:
        await message.answer("Все участники оплатили.")
        return
    rows = [{"Имя": (user_map.get(uid).full_name if user_map.get(uid) else "")} for uid in unpaid_ids]
    await _send_csv(
        message, rows, ["Имя"], "fundbot_unpaid_", f"Не оплатили: {camp.title}"
    )


# ---------------------------------------------------------------------------
# Allowlist management


@router.message(Command("names"))
async def list_names_handler(message: Message) -> None:
    """Show the financier-managed list of allowed surnames."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        names = await list_allowed_names(db)
    if not names:
        await message.answer("Список фамилий пуст. Добавьте: /addname <фамилия>")
        return
    body = "\n".join(f"{i}. {html.escape(n)}" for i, n in enumerate(names, start=1))
    await message.answer(f"<b>Разрешённые фамилии ({len(names)}):</b>\n{body}")


@router.message(Command("addname"))
async def add_name_handler(message: Message, command: CommandObject) -> None:
    """Add a surname to the allowlist."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    name = (command.args or "").strip()
    if not name:
        await message.answer("Использование: /addname <фамилия>")
        return
    async with Session() as db:
        added = await add_allowed_name(db, name)
    if added:
        await message.answer(f"Фамилия «{html.escape(name)}» добавлена.")
    else:
        await message.answer(f"Фамилия «{html.escape(name)}» уже есть в списке.")


@router.message(Command("delname"))
async def del_name_handler(message: Message, command: CommandObject) -> None:
    """Remove a surname from the allowlist."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    name = (command.args or "").strip()
    if not name:
        await message.answer("Использование: /delname <фамилия>")
        return
    async with Session() as db:
        removed = await remove_allowed_name(db, name)
    if removed:
        await message.answer(f"Фамилия «{html.escape(name)}» удалена.")
    else:
        await message.answer(f"Фамилии «{html.escape(name)}» нет в списке.")


# ---------------------------------------------------------------------------
# Remind and broadcast commands


@router.message(Command("remind"))
async def remind_unpaid_handler(message: Message) -> None:
    """Send a reminder to all participants who have not yet paid."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        camp = await get_active_campaign(db)
        if not camp:
            await message.answer("Активного сбора нет.")
            return
        _, unpaid_ids = await list_paid_unpaid(db, camp.id)

    if not unpaid_ids:
        await message.answer("Все участники уже отметили оплату. Напоминания не требуются.")
        return
    reminder_text = (
        f"Напоминание об активном сборе <b>{html.escape(camp.title)}</b>.\n"
        f"Пожалуйста, переведите вашу долю ({camp.per_user_amount}₽) и отметьте это кнопкой в боте."
    )
    sent = await broadcast(message.bot, unpaid_ids, reminder_text)
    await message.answer(f"Напоминания отправлены: {sent}/{len(unpaid_ids)}")


@router.message(Command("message"))
async def broadcast_message_handler(message: Message, command: CommandObject) -> None:
    """
    Broadcast a custom message to all registered users.

    Usage: /message <текст сообщения>
    The text is sent as-is (HTML is supported) to each user in batches.
    """
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    text = (command.args or "").strip()
    if not text:
        await message.answer("Использование: /message <текст сообщения>")
        return
    async with Session() as db:
        users = await get_all_users(db)
    if not users:
        await message.answer("Нет зарегистрированных пользователей.")
        return
    sent = await broadcast(message.bot, [u.id for u in users], text)
    await message.answer(f"Рассылка завершена: {sent}/{len(users)} получателей.")
