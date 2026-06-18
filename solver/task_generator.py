# -*- coding: utf-8 -*-
"""
task_generator.py — Человек 3 — генератор задач (поиск корня f(x)=0).

Строит функцию-линейную комбинацию базиса (x^k, exp, ln, sin, cos), у которой
ГАРАНТИРОВАННО есть вещественный корень: берётся «форма» функции и к ней
добавляется такая константа, чтобы f обращалась в ноль вблизи заранее выбранной
точки r. Истинный корень уточняется ЧИСЛЕННО (методом Ньютона) и проверяется
(f(x*)~0, f'(x*)!=0 — корень простой), а стартовые точки подбираются так, чтобы
оба метода (касательных и секущих) из них сходились.

Зависимости: stdlib + ядро проекта (function_parser, numerical_methods).
"""

import random
from dataclasses import dataclass

import function_parser as _fp
import numerical_methods as _nm


@dataclass
class Task:
    """Сгенерированная задача: выражение, истинный корень и стартовые точки."""
    expression: str
    x_root: float
    f_root: float
    x0: float
    x1: float
    description: str


def _fmt(c: float) -> str:
    """Аккуратный коэффициент: целые без дробной части."""
    return str(int(c)) if c == int(c) else f"{round(c, 3)}"


def _term(coeff: float, body: str) -> str:
    """Слагаемое с ведущим знаком, напр. '+ 2*sin(x)' или '- x^2'."""
    sign = "+" if coeff >= 0 else "-"
    mag = abs(coeff)
    if body == "":                      # константа
        return f"{sign} {_fmt(mag)}"
    if mag == 1:
        return f"{sign} {body}"
    return f"{sign} {_fmt(mag)}*{body}"


class TaskGenerator:
    """Генерирует учебные задачи на поиск корня уравнения f(x)=0."""

    def __init__(self, seed=None):
        self._rng = random.Random(seed)

    def generate(self, complexity: str = "medium") -> Task:
        rng = self._rng
        for _ in range(300):
            use_ln = False
            # Точка, около которой хотим получить корень (для ln держим x>0).
            r = round(rng.uniform(-2.0, 2.0), 2)

            # «Форма» функции без свободного члена. Линейный член a*x (a>0)
            # обеспечивает ненулевую производную и устойчивость методов.
            a = round(rng.uniform(0.8, 2.0), 2)
            terms = [f"{_fmt(a)}*x"]

            if complexity == "easy":
                pass  # просто a*x + const — линейная функция с одним корнем
            elif complexity == "medium":
                k = round(rng.uniform(0.5, 2.0) * rng.choice([-1, 1]), 2)
                terms.append(_term(k, f"{rng.choice(['sin', 'cos'])}(x)"))
            else:  # hard: тригонометрия + exp или ln
                k = round(rng.uniform(0.5, 1.5) * rng.choice([-1, 1]), 2)
                terms.append(_term(k, f"{rng.choice(['sin', 'cos'])}(x)"))
                if rng.random() < 0.5:
                    terms.append(_term(round(rng.uniform(0.05, 0.4), 2), "exp(x)"))
                else:
                    terms.append(_term(round(rng.uniform(0.3, 1.5), 2), "ln(x)"))
                    use_ln = True
                    r = round(rng.uniform(0.5, 2.5), 2)  # ln определён только при x>0

            base_expr = " ".join(terms)
            try:
                base = _fp.Function(base_expr)
                base_at_r = base.f(r)              # значение «формы» в точке r
            except (_fp.ParseError, _fp.EvalError):
                continue

            # Свободный член, чтобы f(r) ~ 0 (округляем для читаемого выражения).
            const = round(-base_at_r, 3)
            expression = base_expr + " " + _term(const, "")
            try:
                func = _fp.Function(expression)
            except _fp.ParseError:
                continue

            # Корень должен быть простым: производная в r заметно ненулевая.
            try:
                if abs(func.df(r)) < 0.3:
                    continue
            except _fp.EvalError:
                continue

            # Уточняем корень численно стартом из r.
            try:
                res = _nm.solve_newton(func, r, tol=1e-12, max_iter=1000)
            except Exception:
                continue
            if not res.converged or res.x_root is None:
                continue
            x_root = res.x_root
            if use_ln and x_root <= 0:
                continue
            try:
                if abs(func.f(x_root)) > 1e-6 or abs(func.df(x_root)) < 0.3:
                    continue
            except _fp.EvalError:
                continue

            # стартовые точки рядом с корнем (но не в нём)
            off = round(rng.uniform(0.3, 0.8), 3)
            x0 = round(x_root - off, 4)
            x1 = round(x_root + off * 0.7, 4)
            if use_ln:
                x0 = round(max(x0, 0.05), 4)
                x1 = round(max(x1, 0.1), 4)
                if x0 == x1:
                    continue

            # оба метода обязаны сходиться из этих точек
            try:
                if not _nm.solve_newton(func, x0, max_iter=1000).converged:
                    continue
                if not _nm.solve_secant(func, x0, x1, max_iter=1000).converged:
                    continue
            except Exception:
                continue

            description = (
                f"f(x) = {func.text}\n"
                f"Истинный корень: x* = {x_root:.6f}, f(x*) = {res.f_root:.2e}\n"
                f"Контроль: f'(x*) = {func.df(x_root):.4f} != 0 (корень простой)"
            )
            return Task(expression, x_root, res.f_root, x0, x1, description)

        raise RuntimeError("Не удалось сгенерировать задачу, попробуйте ещё раз")


if __name__ == "__main__":
    gen = TaskGenerator(seed=1)
    for comp in ("easy", "medium", "hard"):
        for _ in range(2):
            t = gen.generate(comp)
            print(f"[{comp}] {t.expression}")
            print(f"    x_root={t.x_root:.5f}  f_root={t.f_root:.2e}  x0={t.x0}  x1={t.x1}")
