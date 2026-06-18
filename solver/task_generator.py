# -*- coding: utf-8 -*-
"""
task_generator.py — Человек 3 — генератор задач (поиск корня f(x)=0).

Строит функцию вида a*x + k*trig(x) + c, у которой ГАРАНТИРОВАННО есть
вещественный корень: берётся «форма» a*x + k*trig(x) и к ней добавляется такая
константа c, чтобы f обращалась в ноль вблизи заранее выбранной точки r.
Истинный корень уточняется ЧИСЛЕННО (методом Ньютона) и проверяется
(f(x*)~0, f'(x*)!=0 — корень простой), а стартовые точки подбираются так, чтобы
оба метода (касательных и секущих) из них сходились.

Тип генерации один — без уровней сложности.

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

    def generate(self) -> Task:
        rng = self._rng
        for _ in range(300):
            # Точка, около которой хотим получить корень.
            r = round(rng.uniform(-2.0, 2.0), 2)

            # «Форма» функции без свободного члена: линейный член a*x (a>0)
            # обеспечивает ненулевую производную плюс одна тригонометрическая добавка.
            a = round(rng.uniform(0.8, 2.0), 2)
            k = round(rng.uniform(0.5, 2.0) * rng.choice([-1, 1]), 2)
            base_expr = f"{_fmt(a)}*x " + _term(k, f"{rng.choice(['sin', 'cos'])}(x)")

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
            if abs(func.df(r)) < 0.3:
                continue

            # Уточняем корень численно стартом из r.
            try:
                res = _nm.solve_newton(func, r, tol=1e-12, max_iter=1000)
            except Exception:
                continue
            if not res.converged or res.x_root is None:
                continue
            x_root = res.x_root
            if abs(func.f(x_root)) > 1e-6 or abs(func.df(x_root)) < 0.3:
                continue

            # стартовые точки рядом с корнем (но не в нём)
            off = round(rng.uniform(0.3, 0.8), 3)
            x0 = round(x_root - off, 4)
            x1 = round(x_root + off * 0.7, 4)

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
    for _ in range(6):
        t = gen.generate()
        print(t.expression)
        print(f"    x_root={t.x_root:.5f}  f_root={t.f_root:.2e}  x0={t.x0}  x1={t.x1}")
