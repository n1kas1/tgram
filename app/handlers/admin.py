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
from datetime import datetime, timezone
from typing import List

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, FSInputFile

from ..config import settings
from ..db import Session
from ..repo import (
    create_campaign,
    campaign_stats,
    list_by_status,
    list_outstanding,
    get_active_campaign,
    close_active_campaign,
    get_all_users,
    add_allowed_name,
    remove_allowed_name,
    list_allowed_names,
    get_setting,
    set_setting,
    set_campaign_due_date,
    list_campaigns,
    collected_amount,
    user_payment_history,
)
from ..keyboards import payment_kb
from ..models import User, PAYMENT_NONE
from ..utils import broadcast
from ..reports import build_excel_report


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
        requisites = await get_setting(db, "requisites")

    safe_title = html.escape(camp.title)
    await message.answer(
        f"Создан сбор <b>{safe_title}</b> на сумму {camp.total_amount}₽.\n"
        f"Участников: {len(users_ids)}. На каждого: {per_user}₽.\n"
        "Рассылаю уведомления...",
    )

    notice = (
        f"📢 Новый сбор: <b>{safe_title}</b>.\n"
        f"Сколько нужно перевести: {per_user}₽.\n"
    )
    if requisites:
        notice += f"Реквизиты:\n{html.escape(requisites)}\n"
    notice += "Пожалуйста, нажмите кнопку, когда переведёте сумму."

    sent = await broadcast(
        message.bot,
        users_ids,
        notice,
        reply_markup=payment_kb(camp.id, PAYMENT_NONE),
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
        total, confirmed, claimed, unpaid = await campaign_stats(db, camp.id)
        confirmed_ids, claimed_ids, unpaid_ids = await list_by_status(db, camp.id)
        all_users = await get_all_users(db)
        user_map = {u.id: u for u in all_users}

    remain = max(0, camp.total_amount - confirmed * camp.per_user_amount)
    deadline_line = ""
    if camp.due_date:
        deadline_line = f"\nСрок: {camp.due_date.strftime('%d.%m.%Y')}"
    summary = (
        f"📊 Сбор: <b>{html.escape(camp.title)}</b> ({camp.total_amount}₽)"
        f"{deadline_line}\n"
        f"Участников: {total}\n"
        f"Подтверждено: {confirmed}\n"
        f"Ожидают подтверждения: {claimed}\n"
        f"Не оплатили: {unpaid}\n"
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

    await send_list("Подтверждено", confirmed_ids)
    await send_list("Ожидают подтверждения", claimed_ids)
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
        confirmed_ids, claimed_ids, unpaid_ids = await list_by_status(db, camp.id)
    status_label = {}
    for uid in confirmed_ids:
        status_label[uid] = "подтверждено"
    for uid in claimed_ids:
        status_label[uid] = "ожидает подтверждения"
    for uid in unpaid_ids:
        status_label[uid] = "не оплачено"
    rows = []
    for uid in confirmed_ids + claimed_ids + unpaid_ids:
        user = user_map.get(uid)
        rows.append({
            "Имя": user.full_name if user else "",
            "Статус": status_label.get(uid, ""),
        })
    await _send_csv(
        message, rows, ["Имя", "Статус"], "fundbot_", f"Участники сбора {camp.title}"
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
        outstanding_ids = await list_outstanding(db, camp.id)
    if not outstanding_ids:
        await message.answer("Все оплаты подтверждены.")
        return
    rows = [{"Имя": (user_map.get(uid).full_name if user_map.get(uid) else "")} for uid in outstanding_ids]
    await _send_csv(
        message, rows, ["Имя"], "fundbot_unpaid_", f"Не подтверждено: {camp.title}"
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
        outstanding_ids = await list_outstanding(db, camp.id)
        requisites = await get_setting(db, "requisites")

    if not outstanding_ids:
        await message.answer("Все оплаты подтверждены. Напоминания не требуются.")
        return
    reminder_text = (
        f"Напоминание об активном сборе <b>{html.escape(camp.title)}</b>.\n"
        f"Пожалуйста, переведите вашу долю ({camp.per_user_amount}₽) и отметьте это кнопкой в боте."
    )
    if requisites:
        reminder_text += f"\nРеквизиты:\n{html.escape(requisites)}"
    sent = await broadcast(message.bot, outstanding_ids, reminder_text)
    await message.answer(f"Напоминания отправлены: {sent}/{len(outstanding_ids)}")


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


# ---------------------------------------------------------------------------
# Requisites, deadline, history and reports


@router.message(Command("setrequisites"))
async def set_requisites_handler(message: Message, command: CommandObject) -> None:
    """Set the payment requisites shown to participants (or clear them)."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    text = (command.args or "").strip()
    async with Session() as db:
        await set_setting(db, "requisites", text)
    if text:
        await message.answer(f"Реквизиты сохранены:\n{html.escape(text)}")
    else:
        await message.answer("Реквизиты очищены.")


@router.message(Command("deadline"))
async def deadline_handler(message: Message, command: CommandObject) -> None:
    """Set the deadline of the active campaign. Usage: /deadline ДД.ММ.ГГГГ."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    raw = (command.args or "").strip()
    if not raw:
        await message.answer("Использование: /deadline ДД.ММ.ГГГГ (или /deadline -, чтобы убрать)")
        return
    async with Session() as db:
        camp = await get_active_campaign(db)
        if not camp:
            await message.answer("Активного сбора нет.")
            return
        if raw == "-":
            await set_campaign_due_date(db, camp.id, None)
            await message.answer("Срок снят.")
            return
        try:
            due = datetime.strptime(raw, "%d.%m.%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            await message.answer("Неверная дата. Пример: /deadline 31.12.2026")
            return
        await set_campaign_due_date(db, camp.id, due)
    await message.answer(f"Срок сбора установлен: {due.strftime('%d.%m.%Y')}")


@router.message(Command("history"))
async def history_handler(message: Message) -> None:
    """Show past campaigns with collected amounts."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        camps = await list_campaigns(db, limit=20)
        if not camps:
            await message.answer("Сборов ещё не было.")
            return
        lines = ["<b>История сборов:</b>"]
        for c in camps:
            collected = await collected_amount(db, c)
            state = "активен" if c.is_active else "закрыт"
            date = c.created_at.strftime("%d.%m.%Y") if c.created_at else ""
            lines.append(
                f"• {html.escape(c.title)} — собрано {collected}/{c.total_amount}₽ "
                f"({state}, {date})"
            )
    await message.answer("\n".join(lines))


@router.message(Command("report"))
async def report_handler(message: Message) -> None:
    """Export a full Excel report (per-campaign + per-user aggregate)."""
    if not is_financier(message.from_user.id):
        await message.answer("Недоступно.")
        return
    async with Session() as db:
        camps = await list_campaigns(db)
        all_users = await get_all_users(db)
        user_map = {u.id: u for u in all_users}
        campaign_rows = []
        for c in camps:
            collected = await collected_amount(db, c)
            confirmed_ids, claimed_ids, unpaid_ids = await list_by_status(db, c.id)
            campaign_rows.append({
                "title": c.title,
                "total": c.total_amount,
                "per_user": c.per_user_amount,
                "collected": collected,
                "confirmed": len(confirmed_ids),
                "claimed": len(claimed_ids),
                "unpaid": len(unpaid_ids),
                "active": c.is_active,
                "created_at": c.created_at,
                "due_date": c.due_date,
            })
        history = await user_payment_history(db)
    user_rows = []
    for uid, total_c, confirmed_c in history:
        u = user_map.get(uid)
        user_rows.append({
            "name": (u.full_name or u.username or str(uid)) if u else str(uid),
            "campaigns": total_c,
            "confirmed": confirmed_c,
        })

    fd, tmp_path = tempfile.mkstemp(prefix="fundbot_report_", suffix=".xlsx")
    os.close(fd)
    try:
        build_excel_report(tmp_path, campaign_rows, user_rows)
        await message.answer_document(FSInputFile(tmp_path), caption="Отчёт по сборам")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
