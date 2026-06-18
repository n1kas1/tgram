# -*- coding: utf-8 -*-
"""
numerical_methods.py — за этот файл отвечает Человек 2 (методы поиска корня).

Назначение модуля:
    Поиск КОРНЯ уравнения f(x)=0 двумя итерационными методами:
      - метод касательных (Ньютона) — касательные к f(x);
      - метод секущих — секущие к f(x).

Теория (по конспекту):
    Пусть f дифференцируема в окрестности корня x*, f(x*)=0, f'(x)≠0.
    Тогда строится последовательность приближений:
      Ньютон:  x_{n+1} = x_n - f(x_n) / f'(x_n);
      Секущие: x_{n+1} = x_n - f(x_n)·(x_n - x_{n-1}) / (f(x_n) - f(x_{n-1})).
    Метод секущих заменяет производную f'(x_n) разностной оценкой
    (f(x_n) - f(x_{n-1})) / (x_n - x_{n-1}) — вторая производная не нужна.
    Касательные применяют, когда функцию можно продифференцировать;
    секущие — когда дифференцировать неудобно.

    Критерий останова: |f(x)| <= tol ЛИБО |x_{n+1} - x_n| <= tol.
    Лимит — не более 1000 итераций.

Развязка от парсера:
    Функции принимают объект func с методами .f / .df (duck typing),
    но сам модуль НЕ импортирует function_parser — ядро численных методов
    ничего не знает о том, как именно вычисляется функция.

Только стандартная библиотека (math, dataclasses): модуль обязан
импортироваться и тестироваться без GUI и без сторонних пакетов.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Порог вырождения знаменателя: если |f'| (Ньютон) или |Δf| (секущие) меньше,
# итерация неустойчива (деление на почти-ноль) — останавливаемся.
ZERO_DENOM = 1e-14


@dataclass
class RootResult:
    """Результат поиска корня уравнения f(x)=0.

    method:    "newton" | "secant".
    x_root:    найденная точка (float) либо последнее приближение (или None).
    f_root:    значение f в этой точке (или None при неуспехе).
    converged: True, если выполнен критерий точности.
    n_iter:    число выполненных итераций.
    steps:     список шагов (dict) — для таблицы и графика в GUI.
    message:   человекочитаемое пояснение исхода.
    """

    method: str
    x_root: float | None
    f_root: float | None
    converged: bool
    n_iter: int
    steps: list = field(default_factory=list)
    message: str = ""


def _safe(func, x: float) -> tuple[float | None, str | None]:
    """Безопасно вычислить func(x): вернуть (значение, None) или (None, причина).

    Любую доменную/числовую ошибку перехватываем, чтобы метод корректно
    остановился, а не упал. EvalError ловим по ИМЕНИ класса (модуль не
    импортирует парсер). NaN/inf тоже считаем ошибкой.
    """
    try:
        value = func(x)
    except Exception as exc:  # граница ядра: намеренно широкий перехват
        if type(exc).__name__ == "EvalError":
            return None, f"ошибка вычисления: {exc}"
        if isinstance(exc, (ValueError, OverflowError, ZeroDivisionError)):
            return None, f"недопустимая операция: {exc}"
        return None, f"непредвиденная ошибка ({type(exc).__name__}): {exc}"
    if not math.isfinite(value):
        return None, "результат не число (NaN или бесконечность)"
    return float(value), None


def _check_stop(res: RootResult, func, n: int, x_next: float, dx: float,
                tol: float) -> tuple[bool, float | None]:
    """Общий хвост итерации обоих методов после вычисления x_next.

    Возвращает (stop, f_next): stop=True — цикл нужно завершить (res заполнен).
    Проверяет расходимость (нечисловой x_next), ошибки/NaN/inf в f(x_next)
    и критерий точности |dx| <= tol ИЛИ |f(x_next)| <= tol. f_next — значение
    f в x_next (или None, если его не удалось вычислить), чтобы метод мог
    перенести его в следующую итерацию без повторного вызова func.f.
    """
    if not math.isfinite(x_next):
        res.message = f"остановка на итерации {n}: метод расходится (x вышел за пределы чисел)"
        return True, None
    f_next, err = _safe(func.f, x_next)
    if err is not None:
        res.message = f"остановка на итерации {n}: {err} (в точке x_next)"
        return True, None
    if dx <= tol or abs(f_next) <= tol:
        res.x_root, res.f_root, res.converged = x_next, f_next, True
        res.message = f"сошлось за {n} итер.: x={x_next:.12g}, f(x)={f_next:.3e}"
        return True, f_next
    return False, f_next


def solve_newton(func, x0: float, tol: float = 1e-6, max_iter: int = 1000) -> RootResult:
    """Корень f(x)=0 методом касательных (Ньютона): x_{n+1}=x_n - f/f'.

    Останов: |dx| <= tol ИЛИ |f(x_next)| <= tol. Защита: |f'| < ZERO_DENOM
    (касательная горизонтальна), расходимость, ошибки/NaN/inf. При неуспехе
    converged=False.
    """
    res = RootResult("newton", None, None, False, 0, [], "")
    x = float(x0)
    fx, err = _safe(func.f, x)
    if err is not None:
        res.message = f"остановка на старте: {err}"
        return res

    for n in range(1, max_iter + 1):
        res.n_iter = n
        dfx, err = _safe(func.df, x)
        if err is not None:
            res.message = f"остановка на итерации {n}: {err}"
            return res
        if abs(dfx) < ZERO_DENOM:
            res.message = f"остановка на итерации {n}: |f'|<={ZERO_DENOM:.0e} — касательная горизонтальна"
            return res

        x_next = x - fx / dfx
        dx = abs(x_next - x)
        res.steps.append({"n": n, "x": x, "fx": fx, "dfx": dfx, "x_next": x_next, "dx": dx})

        stop, f_next = _check_stop(res, func, n, x_next, dx, tol)
        if stop:
            return res
        x, fx = x_next, f_next  # f(x_next) переносим, чтобы не считать f дважды

    res.x_root, res.f_root = x, fx
    res.message = f"не сошлось за {max_iter} итер. (последнее x={x:.12g})"
    return res


def solve_secant(func, x0: float, x1: float, tol: float = 1e-6, max_iter: int = 1000) -> RootResult:
    """Корень f(x)=0 методом секущих (производная не нужна).

    x_{n+1}=x_n - f(x_n)·(x_n-x_{n-1})/(f(x_n)-f(x_{n-1})). Останов: тот же.
    Защита: |Δf| < ZERO_DENOM (секущая горизонтальна), расходимость,
    ошибки/NaN/inf. При неуспехе converged=False.
    """
    res = RootResult("secant", None, None, False, 0, [], "")
    x_prev, x_curr = float(x0), float(x1)

    f_prev, err = _safe(func.f, x_prev)
    if err is None:
        f_curr, err = _safe(func.f, x_curr)
    if err is not None:
        res.message = f"остановка на старте: {err}"
        return res

    for n in range(1, max_iter + 1):
        res.n_iter = n
        denom = f_curr - f_prev
        if abs(denom) < ZERO_DENOM:
            res.message = f"остановка на итерации {n}: |Δf|<={ZERO_DENOM:.0e} — секущая горизонтальна"
            return res

        x_next = x_curr - f_curr * (x_curr - x_prev) / denom
        dx = abs(x_next - x_curr)
        res.steps.append({"n": n, "x_prev": x_prev, "x_curr": x_curr,
                          "f_prev": f_prev, "f_curr": f_curr, "x_next": x_next, "dx": dx})

        stop, f_next = _check_stop(res, func, n, x_next, dx, tol)
        if stop:
            return res
        x_prev, f_prev = x_curr, f_curr
        x_curr, f_curr = x_next, f_next

    res.x_root, res.f_root = x_curr, f_curr
    res.message = f"не сошлось за {max_iter} итер. (последнее x={x_curr:.12g})"
    return res


if __name__ == "__main__":
    # Самопроверка на мини-объектах с .f/.df (без участия парсера).
    class _Quad:
        """f(x)=x^2-2 — корни ±sqrt(2)."""

        def f(self, x: float) -> float:
            return x * x - 2.0

        def df(self, x: float) -> float:
            return 2.0 * x

    class _Cubic:
        """f(x)=x^3-2x-5 — единственный вещественный корень ≈ 2.0945515."""

        def f(self, x: float) -> float:
            return x ** 3 - 2.0 * x - 5.0

        def df(self, x: float) -> float:
            return 3.0 * x * x - 2.0

    r = solve_newton(_Quad(), x0=1.0)
    print("newton x^2-2:", r.x_root, r.converged, r.message)
    assert r.converged and abs(r.x_root - math.sqrt(2)) < 1e-6

    r = solve_secant(_Quad(), x0=2.0, x1=1.0)
    print("secant x^2-2:", r.x_root, r.converged, r.message)
    assert r.converged and abs(r.x_root - math.sqrt(2)) < 1e-6

    # Пример из конспекта: x^3-2x-5, старт x0=1 (Ньютон) — корень ≈ 2.0945515.
    r = solve_newton(_Cubic(), x0=1.0)
    print("newton x^3-2x-5:", r.x_root, r.converged, r.message)
    assert r.converged and abs(r.x_root - 2.0945514815) < 1e-6

    # Тот же пример методом секущих со стартами из конспекта (x0=3, x1=1).
    r = solve_secant(_Cubic(), x0=3.0, x1=1.0)
    print("secant x^3-2x-5:", r.x_root, r.converged, r.message)
    assert r.converged and abs(r.x_root - 2.0945514815) < 1e-6

    print("Все самопроверки пройдены успешно.")
