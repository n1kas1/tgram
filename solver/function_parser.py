# -*- coding: utf-8 -*-
"""
function_parser.py — за этот файл отвечает Человек 1 (разбор функции из текста).

Назначение:
    Разобрать строку в ЛИНЕЙНУЮ КОМБИНАЦИЮ базисных функций и дать значение f(x)
    и АНАЛИТИЧЕСКУЮ производную f'(x) — потабличным дифференцированием.

Базис (никаких произведений функций, никакого общего AST):
    константа, x^k (k — целое >= 1), exp(x), ln(x)=log(x), sin(x), cos(x).
    Пример: "x^2 - 3*sin(x) + 0.5*exp(x) - 2".

Внутреннее представление слагаемого — кортеж (coeff, kind, power):
    kind in {"const","pow","exp","ln","sin","cos"};
    для "pow" power=k (производные допускают k<=0); для остальных power=None.

Только стандартная библиотека: math, re.
"""

from __future__ import annotations

import math
import re

# Тип слагаемого: (коэффициент, вид, степень|None).
Term = tuple[float, str, "int | None"]

# Имена функций -> внутренний kind (log трактуем как ln).
_FUNCS = {"exp": "exp", "ln": "ln", "log": "ln", "sin": "sin", "cos": "cos"}


class ParseError(Exception):
    """Ошибка разбора строки (пустой ввод, неизвестный токен, мусор, скобка не вокруг x)."""


class EvalError(Exception):
    """Ошибка вычисления (ln при x<=0, x в отрицательной степени при x=0, переполнение exp)."""


# --- Регулярки для одного слагаемого (без ведущего знака) ----------------------
# Число: 2, 2.5, .5, 1e-3 и т.п. Экспоненциальная форма стоит ПЕРВОЙ, чтобы
# мантисса не «откусывалась» более коротким вариантом без обратного хода.
_NUM = r"\d+\.?\d*[eE][+-]?\d+|\d+\.?\d*|\.\d+"
# Слагаемое-степень: [c][*]x[^k]  — коэффициент и степень необязательны.
_POW = re.compile(rf"^(?:({_NUM})\*?)?x(?:\^(\d+))?$")
# Слагаемое-функция: [c][*]func(arg)
_FUN = re.compile(rf"^(?:({_NUM})\*?)?([a-z]+)\(([^()]*)\)$")
# Чистая константа.
_CONST = re.compile(rf"^({_NUM})$")


def _split_terms(text: str) -> list[tuple[str, str]]:
    """Разбить выражение на список (знак, тело-слагаемого) по +/- верхнего уровня.

    Скобки бывают только внутри func(x), а +/- внутри них по условию не встречаются,
    поэтому достаточно линейного прохода с подсчётом глубины скобок.
    """
    if not isinstance(text, str):
        raise ParseError("Ожидалась строка с выражением")
    s = text.replace(" ", "")
    if not s:
        raise ParseError("Пустой ввод")
    terms: list[tuple[str, str]] = []
    sign, buf, depth = "+", "", 0
    # Ведущий знак, если есть.
    i = 0
    if s[0] in "+-":
        sign, i = s[0], 1
    while i < len(s):
        ch = s[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ParseError("Лишняя закрывающая скобка")
        if ch in "+-" and depth == 0:
            if not buf:
                raise ParseError("Пустое слагаемое")
            terms.append((sign, buf))
            sign, buf = ch, ""
        else:
            buf += ch
        i += 1
    if depth != 0:
        raise ParseError("Незакрытая скобка")
    if not buf:
        raise ParseError("Выражение обрывается знаком")
    terms.append((sign, buf))
    return terms


def _parse_term(sign: str, body: str) -> Term:
    """Разобрать одно слагаемое в кортеж (coeff, kind, power)."""
    s = -1.0 if sign == "-" else 1.0

    m = _CONST.match(body)
    if m:
        return (s * float(m.group(1)), "const", None)

    m = _POW.match(body)
    if m:
        coeff = float(m.group(1)) if m.group(1) is not None else 1.0
        power = int(m.group(2)) if m.group(2) is not None else 1
        if power < 1:
            raise ParseError(f"Степень должна быть >= 1: '{body}'")
        return (s * coeff, "pow", power)

    m = _FUN.match(body)
    if m:
        coeff = float(m.group(1)) if m.group(1) is not None else 1.0
        name, arg = m.group(2), m.group(3)
        if name not in _FUNCS:
            raise ParseError(f"Неизвестная функция: '{name}'")
        if arg != "x":  # скобка обязана содержать ровно x
            raise ParseError(f"Аргумент функции должен быть x, а не '{arg}'")
        return (s * coeff, _FUNCS[name], None)

    raise ParseError(f"Не удалось разобрать слагаемое: '{body}'")


def _eval_terms(terms: list[Term], x: float) -> float:
    """Вычислить сумму слагаемых в точке x (потабличные значения базиса)."""
    total = 0.0
    for coeff, kind, power in terms:
        if kind == "const":
            total += coeff
        elif kind == "pow":
            if power < 0 and x == 0.0:
                raise EvalError("Отрицательная степень x при x=0")
            total += coeff * (x**power)
        elif kind == "exp":
            try:
                total += coeff * math.exp(x)
            except OverflowError as e:
                raise EvalError("Переполнение exp(x)") from e
        elif kind == "ln":
            if x <= 0.0:
                raise EvalError("ln(x) при x<=0")
            total += coeff * math.log(x)
        elif kind == "sin":
            total += coeff * math.sin(x)
        elif kind == "cos":
            total += coeff * math.cos(x)
    return total


def _diff_terms(terms: list[Term]) -> list[Term]:
    """Потабличная производная списка слагаемых -> новый список (базис замкнут)."""
    out: list[Term] = []
    for coeff, kind, power in terms:
        if kind == "const":
            continue  # производная константы — 0
        elif kind == "pow":
            new_c, new_p = coeff * power, power - 1
            out.append((new_c, "const", None) if new_p == 0 else (new_c, "pow", new_p))
        elif kind == "exp":
            out.append((coeff, "exp", None))
        elif kind == "ln":
            out.append((coeff, "pow", -1))  # (ln x)' = x^(-1)
        elif kind == "sin":
            out.append((coeff, "cos", None))
        elif kind == "cos":
            out.append((-coeff, "sin", None))
    return out


def _fmt_coeff(coeff: float) -> str:
    """Целые печатаем без дробной части, иначе обычное представление."""
    return str(int(coeff)) if coeff == int(coeff) else repr(coeff)


def _terms_to_text(terms: list[Term]) -> str:
    """Собрать читаемую строку из слагаемых (опускаем нули и единичные coeff)."""
    parts: list[tuple[str, str]] = []
    for coeff, kind, power in terms:
        if coeff == 0.0:
            continue
        sign = "-" if coeff < 0 else "+"
        mag = abs(coeff)
        # тело слагаемого без коэффициента
        if kind == "const":
            body, drop_one = "", False  # для const "1" печатать НАДО
        elif kind == "pow":
            # power всегда != 0: парсер требует k>=1, а дифференцирование степени
            # с power==1 даёт уже const (см. _diff_terms), не pow.
            body = "x" if power == 1 else f"x^{power}"
            drop_one = True
        elif kind == "exp":
            body, drop_one = "exp(x)", True
        elif kind == "ln":
            body, drop_one = "ln(x)", True
        elif kind == "sin":
            body, drop_one = "sin(x)", True
        else:  # cos
            body, drop_one = "cos(x)", True
        if not body:  # чистая константа
            token = _fmt_coeff(mag)
        elif mag == 1.0 and drop_one:
            token = body
        else:
            token = f"{_fmt_coeff(mag)}*{body}"
        parts.append((sign, token))
    if not parts:
        return "0"
    # первый член: знак "+" опускаем
    first_sign, first_tok = parts[0]
    out = ("-" + first_tok) if first_sign == "-" else first_tok
    for sign, tok in parts[1:]:
        out += f" {sign} {tok}"
    return out


class Function:
    """Разобранная функция: значение и аналитическая производная по линейной комбинации."""

    def __init__(self, text: str) -> None:
        self._terms = [_parse_term(sign, body) for sign, body in _split_terms(text)]
        self._d1 = _diff_terms(self._terms)
        self.text = _terms_to_text(self._terms)
        self.df_text = _terms_to_text(self._d1)

    def f(self, x: float) -> float:
        return _eval_terms(self._terms, x)

    def df(self, x: float) -> float:
        return _eval_terms(self._d1, x)

    def __repr__(self) -> str:
        return f"Function({self.text!r})"


if __name__ == "__main__":
    # --- Самопроверки ----------------------------------------------------------
    g = Function("x^2 - 3*sin(x) + 2")
    print("f      =", g.text)
    print("f'     =", g.df_text)
    x0 = 1.0
    print(f"f({x0})   = {g.f(x0):.6f}")
    print(f"f'({x0})  = {g.df(x0):.6f}")

    # Сверка аналитической df с центральной разностью.
    h = 1e-5
    num = (g.f(x0 + h) - g.f(x0 - h)) / (2 * h)
    print(f"df аналит = {g.df(x0):.6f}, df числ = {num:.6f}, |Δ| = {abs(g.df(x0) - num):.2e}")
    assert abs(g.df(x0) - num) < 1e-6, "df не совпала с численной производной"

    # Неявное умножение и константы.
    g2 = Function("2x^3 + 0.5exp(x) - ln(x) + cos(x) - 4")
    print("\nf2     =", g2.text)
    print("f2'    =", g2.df_text)

    # Ошибки разбора и вычисления.
    for bad in ["", "x +", "tan(x)", "sin(y)", "x^0"]:
        try:
            Function(bad)
            print(f"ОШИБКА: '{bad}' разобралось без исключения")
        except ParseError:
            pass
    try:
        Function("ln(x)").f(-1.0)
        print("ОШИБКА: ln(-1) не дало EvalError")
    except EvalError:
        pass
    print("\nВсе самопроверки пройдены.")
