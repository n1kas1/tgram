from __future__ import annotations

"""
Handlers for financier-only commands.

This module contains commands that are restricted to users designated as
financiers.  Financiers can create and manage fundraising campaigns,
inspect participant lists, export CSV reports, and close active campaigns.
"""

import asyncio
from datetime import datetime
from typing import List
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, FSInputFile
from aiogram.exceptions import TelegramRetryAfter

from ..config import settings
from ..db import Session
from ..repo import (
    create_campaign,
    campaign_stats,
    list_paid_unpaid,
    get_active_campaign,
    close_active_campaign,
    get_all_users,
    list_user_ids,
)
from ..keyboards import payment_kb
from ..models import User


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

    The ``amount`` should be an integer representing the total number of
    rubles to collect.  The ``title`` may contain spaces and should describe
    the campaign.  All registered users (except the financier) will receive
    a notification with a button to mark their payment when the campaign is
    created.
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
    title = parts[1].strip().strip('"') if len(parts) > 1 else f"Сбор #{datetime.now().strftime('%Y-%m-%d')}"

    async with Session() as db:
        camp, users_ids, per_user = await create_campaign(db, title, total, message.from_user.id)

    await message.answer(
        f"Создан сбор <b>{camp.title}</b> на сумму {camp.total_amount}₽.\n"
        f"Участников: {len(users_ids)}. На каждого: {per_user}₽.\n"
        f"Рассылаю уведомления...",
        parse_mode="HTML",
    )

    sent = 0
    batch_size = max(1, settings.BATCH)
    for i, uid in enumerate(users_ids, start=1):
        try:
            await message.bot.send_message(
                uid,
                f"📢 Новый сбор: <b>{camp.title}</b>.\n"
                f"Ваша доля: {per_user}₽.\n"
                "Пожалуйста, нажмите кнопку, когда переведёте сумму.",
                reply_markup=payment_kb(camp.id, False),
                parse_mode="HTML",
            )
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception:
            pass
        if i % batch_size == 0:
            await asyncio.sleep(0.5)

    await message.answer(f"Уведомления отправлены: {sent}/{len(users_ids)}")


@router.message(Command("dash"))
async def dashboard_handler(message: Message) -> None:
    """
    Display statistics and lists for the active campaign.
    """
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
        f"📊 Сбор: <b>{camp.title}</b> ({camp.total_amount}₽)\n"
        f"Участников: {total}\n"
        f"Оплатили: {paid_count}\n"
        f"Не оплатили: {unpaid_count}\n"
        f"Осталось собрать ≈ {remain}₽"
    )
    await message.answer(summary, parse_mode="HTML")

    def fmt(uid: int) -> str:
        u = user_map.get(uid)
        if u:
            name = u.full_name or u.username or str(uid)
        else:
            name = str(uid)
        return f'<a href="tg://user?id={uid}">{name}</a>'

    async def send_list(title: str, ids: List[int]) -> None:
        if not ids:
            await message.answer(f"{title}: нет пользователей.")
            return
        lines = [fmt(i) for i in ids]
        chunk_size = 50
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i : i + chunk_size]
            await message.answer(
                f"{title}:\n" + "\n".join(chunk),
                parse_mode="HTML",
            )

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


@router.message(Command("csv"))
async def export_csv_handler(message: Message) -> None:
    """
    Export the participant list of the active campaign as a CSV file.
    """
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
    rows = []
    for uid in paid_ids + unpaid_ids:
        user = user_map.get(uid)
        rows.append({
            "тг_id": uid,
            "Имя": user.full_name if user else "",
            "Никнейм": user.username if user else "",
            "Оплачено": "да" if uid in paid_ids else "нет",
        })
    import csv, tempfile, os
    fd, tmp_path = tempfile.mkstemp(prefix="fundbot_", suffix=".csv")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["тг_id", "Имя", "Никнейм", "Оплачено"])
        writer.writeheader()
        writer.writerows(rows)
    await message.answer_document(FSInputFile(tmp_path), caption=f"Участники сбора {camp.title}")


@router.message(Command("users"))
async def list_users_handler(message: Message) -> None:
    """
    List all registered users with links to their Telegram accounts.
    """
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        users = await get_all_users(db)
    # Group users by role and enumerate them
    financiers = [u for u in users if u.is_financier]
    participants = [u for u in users if not u.is_financier]

    def fmt_user(u: User, idx: int) -> str:
        name = u.full_name or u.username or str(u.id)
        role = "финансист" if u.is_financier else "участник"
        return f"{idx}. <a href=\"tg://user?id={u.id}\">{name}</a> – {role}"

    lines: List[str] = []
    idx = 1
    for u in financiers:
        lines.append(fmt_user(u, idx))
        idx += 1
    for u in participants:
        lines.append(fmt_user(u, idx))
        idx += 1
    # Send the list in chunks to avoid exceeding message limits
    chunk_size = 40
    for i in range(0, len(lines), chunk_size):
        chunk = lines[i : i + chunk_size]
        await message.answer("\n".join(chunk), parse_mode="HTML")


@router.message(Command("unpaid"))
async def export_unpaid_handler(message: Message) -> None:
    """
    Export the list of users who have not paid as a CSV file.
    """
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
    rows = []
    for uid in unpaid_ids:
        user = user_map.get(uid)
        rows.append({
            "тг_id": uid,
            "Имя": user.full_name if user else "",
            "Никнейм": user.username if user else "",
        })
    import csv, tempfile, os
    fd, tmp_path = tempfile.mkstemp(prefix="fundbot_unpaid_", suffix=".csv")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["тг_id", "Имя", "Никнейм"])
        writer.writeheader()
        writer.writerows(rows)
    await message.answer_document(FSInputFile(tmp_path), caption=f"Не оплатили: {camp.title}")


# ---------------------------------------------------------------------------
# Remind and broadcast commands


@router.message(Command("remind"))
async def remind_unpaid_handler(message: Message) -> None:
    """
    Send a reminder to all participants who have not yet marked their payment in the active campaign.
    Only financiers can invoke this command.  The reminder will be sent to each unpaid user with a
    brief note and instructions.
    """
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        camp = await get_active_campaign(db)
        if not camp:
            await message.answer("Активного сбора нет.")
            return
        paid_ids, unpaid_ids = await list_paid_unpaid(db, camp.id)
        all_users = await get_all_users(db)
        user_map = {u.id: u for u in all_users}

    if not unpaid_ids:
        await message.answer("Все участники уже отметили оплату. Напоминания не требуются.")
        return
    # Compose the reminder message
    reminder_text = (
        f"Напоминание об активном сборе <b>{camp.title}</b>.\n"
        f"Пожалуйста, переведите вашу долю ({camp.per_user_amount}₽) и отметьте это в боте, нажав кнопку."
    )
    sent = 0
    batch_size = max(1, settings.BATCH)
    for i, uid in enumerate(unpaid_ids, start=1):
        try:
            await message.bot.send_message(uid, reminder_text, parse_mode="HTML")
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception:
            pass
        if i % batch_size == 0:
            await asyncio.sleep(0.5)
    await message.answer(f"Напоминания отправлены: {sent}/{len(unpaid_ids)}")


@router.message(Command("message"))
async def broadcast_message_handler(message: Message, command: CommandObject) -> None:
    """
    Broadcast a custom message to all registered users.
    Usage: /message <текст сообщения>
    Only financiers can use this command.  The provided text will be sent as-is (HTML is supported)
    to each user in batches.  If no text is provided, the bot will reply with instructions.
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
    sent = 0
    batch_size = max(1, settings.BATCH)
    for i, u in enumerate(users, start=1):
        # Do not send to the financier themselves multiple times if there are multiple financiers; but send anyway.
        try:
            await message.bot.send_message(u.id, text, parse_mode="HTML")
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception:
            pass
        if i % batch_size == 0:
            await asyncio.sleep(0.5)
    await message.answer(f"Рассылка завершена: {sent}/{len(users)} получателей.")
