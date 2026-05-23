"""One-time seed data for the surname allowlist.

These names previously lived (and were validated) inline in the handlers.
They are now seeded into the ``allowed_names`` table on first startup, after
which the financier manages the list at runtime via ``/addname`` / ``/delname``.
"""

from __future__ import annotations

SEED_NAMES: list[str] = [
    "Агеев",
    "Ананич",
    "Атаманчук",
    "Бакиров",
    "Балажегитов",
    "Баринов",
    "Болтышев",
    "Васьков",
    "Ведяшкин",
    "Воронов",
    "Вчерашний",
    "Гончаров",
    "Гололобов",
    "Дёмин",
    "Дуняшев",
    "Дьячков",
    "Ефимов",
    "Забрамский",
    "Зданович",
    "Золкин",
    "Иванов",
    "Камаев",
    "Кирюхин",
    "Коваль",
    "Куранов",
    "Куцев",
    "Матковский",
    "Никифоров",
    "Пилюгаев",
    "Плахов",
    "Побережный",
    "Претцер",
    "Рыбак",
    "Сакунов",
    "Семерьянов",
    "Толкачев",
    "Хлебников",
    "Шаповалов",
    "Шмыков",
    "Щекудов",
]
