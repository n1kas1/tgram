# -*- coding: utf-8 -*-
"""
gui.py — Человек 4 — графический интерфейс (PyQt5 + встроенный график matplotlib).

ПРОСТОЕ настольное окно для поиска КОРНЯ уравнения f(x)=0 методами касательных
(Ньютона) и секущих. Других режимов нет — приложение всегда ищет корень.

GUI не содержит численной логики — он только вызывает ядро и показывает результат:
таблицу итераций и встроенный график (кривая f, точки итераций, звезда-корень).

Ядро (по контракту):
  * function_parser.Function       — разбор выражения, аналитические производные;
  * numerical_methods.solve_newton — касательные к f (корень = решение f(x)=0);
  * numerical_methods.solve_secant — секущие к f;
  * task_generator.TaskGenerator   — генерация учебных задач (поиск корня).

Целевая ОС — Windows. Используются PyQt5, matplotlib и numpy. Стиль — Fusion.
"""

import os
import sys


def _ensure_qt_plugin_path() -> None:
    """Подсказывает Qt путь к платформенному плагину (на Windows — qwindows.dll).

    Без этого в перенесённых окружениях возможна ошибка
    'qt.qpa.plugin: Could not load the Qt platform plugin "windows"'.
    Переменные окружения ставим ДО создания QApplication; setdefault не
    перетирает значение, заданное пользователем вручную.
    """
    try:
        import PyQt5

        base = os.path.dirname(PyQt5.__file__)
        for sub in ("Qt5", "Qt"):
            plugins = os.path.join(base, sub, "plugins")
            platforms = os.path.join(plugins, "platforms")
            if os.path.isdir(platforms):
                os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", platforms)
                os.environ.setdefault("QT_PLUGIN_PATH", plugins)
                break
    except Exception:
        pass


_ensure_qt_plugin_path()

import numpy as np

# --- Контракт импортов из ядра (дословно) -----------------------------------
from function_parser import Function, ParseError, EvalError
from numerical_methods import solve_newton, solve_secant, RootResult
from task_generator import TaskGenerator, Task

# --- Matplotlib, встроенный в Qt --------------------------------------------
import matplotlib

matplotlib.use("Qt5Agg")  # backend задаём до импорта canvas
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# --- PyQt5 ------------------------------------------------------------------
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Подпись метода в выпадающем списке -> внутренний ключ.
METHODS = {
    "Метод касательных (Ньютона)": "newton",
    "Метод секущих": "secant",
}


def _fmt(value) -> str:
    """Аккуратная строка для числа в таблице/подписях (или '—' для None)."""
    if value is None:
        return "—"
    try:
        return f"{float(value):.8g}"
    except (TypeError, ValueError):
        return str(value)


class MainWindow(QMainWindow):
    """Главное окно: ввод/генерация функции, параметры, таблица и график."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Поиск корня f(x)=0: касательные и секущие")
        self.resize(1180, 760)

        self.func: Function | None = None  # последняя успешно разобранная функция
        self.result: RootResult | None = None  # последний результат поиска корня
        self._generator = TaskGenerator()  # один экземпляр на сессию
        self._last_task: Task | None = None

        # Корневой горизонтальный сплиттер: слева панель управления, справа график.
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 660])
        self.setCentralWidget(splitter)

    # ------------------------------------------------------------------ layout
    def _build_left_panel(self) -> QWidget:
        """Левая колонка: функция, генератор, параметры, таблица итераций."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self._build_function_box())
        layout.addWidget(self._build_generator_box())
        layout.addWidget(self._build_params_box())
        layout.addWidget(self._build_table_box(), stretch=1)
        return panel

    def _build_function_box(self) -> QGroupBox:
        box = QGroupBox("Функция f(x)")
        v = QVBoxLayout(box)

        self.expr_edit = QLineEdit()
        self.expr_edit.setPlaceholderText("x^3 - 2*x - 5")
        v.addWidget(self.expr_edit)

        row = QHBoxLayout()
        btn_parse = QPushButton("Разобрать")
        btn_parse.clicked.connect(self.on_parse)
        btn_load = QPushButton("Загрузить из файла")
        btn_load.clicked.connect(self.on_load_file)
        row.addWidget(btn_parse)
        row.addWidget(btn_load)
        v.addLayout(row)

        # Многострочный вывод: f, f'.
        self.derivs_view = QTextEdit()
        self.derivs_view.setReadOnly(True)
        self.derivs_view.setMaximumHeight(96)
        self.derivs_view.setPlaceholderText(
            "Базис: константа, x^k (k>=1), exp(x), ln(x), sin(x), cos(x). "
            "Пример: x^3 - 2*x - 5"
        )
        v.addWidget(self.derivs_view)
        return box

    def _build_generator_box(self) -> QGroupBox:
        box = QGroupBox("Генератор задачи (корень f(x)=0)")
        row = QHBoxLayout(box)

        btn_gen = QPushButton("Сгенерировать")
        btn_gen.clicked.connect(self.on_generate)
        row.addWidget(btn_gen)

        self.show_answer_chk = QCheckBox("Показать ответ")
        row.addWidget(self.show_answer_chk)
        row.addStretch(1)
        return box

    def _build_params_box(self) -> QGroupBox:
        box = QGroupBox("Параметры поиска корня")
        v = QVBoxLayout(box)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Метод:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems(list(METHODS.keys()))
        self.method_combo.currentTextChanged.connect(self._on_method_changed)
        r1.addWidget(self.method_combo, stretch=1)
        v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("x0:"))
        self.x0_spin = self._make_double_spin(default=1.0)
        r2.addWidget(self.x0_spin)

        self.x1_label = QLabel("x1:")
        r2.addWidget(self.x1_label)
        self.x1_spin = self._make_double_spin(default=1.2)
        r2.addWidget(self.x1_spin)
        v.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Точность tol:"))
        self.tol_spin = QDoubleSpinBox()
        self.tol_spin.setDecimals(12)
        self.tol_spin.setRange(1e-14, 1.0)
        self.tol_spin.setSingleStep(1e-7)
        self.tol_spin.setValue(1e-6)
        r3.addWidget(self.tol_spin)

        r3.addWidget(QLabel("Макс. итераций:"))
        self.maxiter_spin = QSpinBox()
        self.maxiter_spin.setRange(1, 1_000_000)
        self.maxiter_spin.setValue(1000)
        r3.addWidget(self.maxiter_spin)
        v.addLayout(r3)

        btn_solve = QPushButton("Найти корень")
        btn_solve.clicked.connect(self.on_solve)
        v.addWidget(btn_solve)

        self.result_label = QLabel("Результат появится здесь.")
        self.result_label.setWordWrap(True)
        v.addWidget(self.result_label)

        # Стартовая видимость поля x1 зависит от выбранного метода.
        self._on_method_changed(self.method_combo.currentText())
        return box

    @staticmethod
    def _make_double_spin(default: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(6)
        spin.setRange(-1e6, 1e6)
        spin.setSingleStep(0.1)
        spin.setValue(default)
        return spin

    def _build_table_box(self) -> QGroupBox:
        box = QGroupBox("Итерации метода")
        v = QVBoxLayout(box)
        self.table = QTableWidget(0, 5)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.table)
        return box

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        self.figure = Figure(figsize=(6, 5))
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self._draw_empty()
        v.addWidget(self.canvas)
        return panel

    # ----------------------------------------------------------------- helpers
    def _on_method_changed(self, label: str) -> None:
        """Показываем поле x1 только для метода секущих."""
        is_secant = METHODS.get(label) == "secant"
        self.x1_label.setVisible(is_secant)
        self.x1_spin.setVisible(is_secant)

    def _current_method(self) -> str:
        return METHODS.get(self.method_combo.currentText(), "newton")

    def _parse_expr(self) -> bool:
        """Разобрать текущее выражение в self.func. True при успехе.

        При ошибке показывает диалог и оставляет self.func без изменения вызова.
        """
        text = self.expr_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "Пустой ввод", "Введите или сгенерируйте функцию.")
            return False
        try:
            self.func = Function(text)
        except ParseError as exc:
            QMessageBox.critical(self, "Ошибка разбора", f"Не удалось разобрать функцию:\n{exc}")
            return False
        except Exception as exc:  # noqa: BLE001 — не роняем GUI на неожиданном
            QMessageBox.critical(self, "Ошибка", f"Непредвиденная ошибка разбора:\n{exc}")
            return False
        return True

    # ------------------------------------------------------------------ events
    def on_parse(self) -> None:
        """Разобрать выражение и показать f, f'."""
        if not self._parse_expr():
            return
        self.derivs_view.setPlainText(
            f"f(x)  = {self.func.text}\n"
            f"f'(x) = {self.func.df_text}"
        )

    def on_load_file(self) -> None:
        """Загрузить выражение из .txt (берём первую непустую строку)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть файл с функцией", "", "Текстовые файлы (*.txt);;Все файлы (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                first = ""
                for line in fh:
                    if line.strip():
                        first = line.strip()
                        break
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка файла", f"Не удалось прочитать файл:\n{exc}")
            return
        if not first:
            QMessageBox.warning(self, "Пустой файл", "В файле нет непустых строк.")
            return
        self.expr_edit.setText(first)
        self.on_parse()

    def on_generate(self) -> None:
        """Сгенерировать учебную задачу на поиск корня f(x)=0."""
        try:
            task = self._generator.generate()
        except Exception as exc:  # генератор может бросить ValueError/RuntimeError
            QMessageBox.critical(self, "Ошибка генерации", f"Не удалось сгенерировать задачу:\n{exc}")
            return

        self._last_task = task
        self.expr_edit.setText(task.expression)
        self.x0_spin.setValue(float(task.x0))
        self.x1_spin.setValue(float(task.x1))
        self.on_parse()

        if self.show_answer_chk.isChecked():
            self.result_label.setText(
                f"Задача: {task.description}\n"
                f"Ответ (скрываемый): x_root = {_fmt(task.x_root)}, "
                f"f(x_root) = {_fmt(task.f_root)}"
            )
        else:
            self.result_label.setText(f"Задача: {task.description}")

    def on_solve(self) -> None:
        """Запустить выбранный метод поиска корня и показать таблицу + график."""
        # Берём актуальное выражение (вдруг отредактировали после «Разобрать»).
        if not self._parse_expr():
            return

        method = self._current_method()
        x0 = float(self.x0_spin.value())
        x1 = float(self.x1_spin.value())
        tol = float(self.tol_spin.value())
        max_iter = int(self.maxiter_spin.value())

        try:
            if method == "newton":
                result = solve_newton(self.func, x0, tol=tol, max_iter=max_iter)
            else:
                if abs(x0 - x1) < 1e-12:
                    QMessageBox.warning(
                        self, "Совпадающие точки",
                        "Для метода секущих x0 и x1 должны различаться."
                    )
                    return
                result = solve_secant(self.func, x0, x1, tol=tol, max_iter=max_iter)
        except (EvalError, ValueError) as exc:
            QMessageBox.critical(self, "Ошибка вычисления", f"Метод не смог отработать:\n{exc}")
            return
        except Exception as exc:  # noqa: BLE001 — последний рубеж, чтобы не падать
            QMessageBox.critical(self, "Ошибка", f"Непредвиденная ошибка метода:\n{exc}")
            return

        self.result = result
        self._show_result(result)
        self._fill_table(result, method)
        try:
            self._plot(result, method)
        except Exception as exc:  # noqa: BLE001 — график не должен ронять расчёт
            QMessageBox.warning(self, "График", f"Не удалось построить график:\n{exc}")

    # ------------------------------------------------------------------ result
    def _show_result(self, result: RootResult) -> None:
        status = "сошлось" if result.converged else "НЕ сошлось"
        self.result_label.setText(
            f"x_root = {_fmt(result.x_root)}    f(x_root) = {_fmt(result.f_root)}\n"
            f"Итераций: {result.n_iter}    Статус: {status}\n"
            f"{result.message}"
        )

    def _fill_table(self, result: RootResult, method: str) -> None:
        """Заполнить таблицу итераций колонками под выбранный метод.

        Корень ищется как решение f(x)=0. Ключи шагов известны из
        numerical_methods:
          newton: n, x, fx (=f), dfx (=f'), dx;
          secant: n, x_prev, x_curr, f_prev (=f), f_curr (=f), dx.
        """
        steps = result.steps or []
        if method == "newton":
            headers = ["n", "x", "f(x)", "f'(x)", "|dx|"]
            keys = ("x", "fx", "dfx", "dx")
        else:
            headers = ["n", "x_(n-1)", "x_n", "f(x_(n-1))", "f(x_n)", "|dx|"]
            keys = ("x_prev", "x_curr", "f_prev", "f_curr", "dx")

        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(steps))

        for i, step in enumerate(steps):
            row = [str(step.get("n", i + 1))]
            row += [_fmt(step.get(k)) for k in keys]
            for j, value in enumerate(row):
                self.table.setItem(i, j, QTableWidgetItem(value))

    @staticmethod
    def _safe_eval(fn, x) -> float | None:
        """Безопасно вычислить fn(x): любая ошибка -> None (точка пропускается)."""
        try:
            value = fn(float(x))
        except Exception:  # noqa: BLE001
            return None
        return value if np.isfinite(value) else None

    # -------------------------------------------------------------------- plot
    def _draw_empty(self) -> None:
        self.ax.clear()
        self.ax.set_title("График f(x)")
        self.ax.set_xlabel("x")
        self.ax.set_ylabel("f(x)")
        self.ax.grid(True, alpha=0.3)
        self.ax.text(
            0.5, 0.5, "Здесь появится график f(x)",
            ha="center", va="center", transform=self.ax.transAxes, color="gray"
        )
        self.canvas.draw_idle()

    @staticmethod
    def _step_x(step: dict, method: str) -> float | None:
        """x-приближение шага: для Ньютона — 'x', для секущих — текущее 'x_curr'."""
        val = step.get("x") if method == "newton" else step.get("x_curr")
        if val is None:
            return None
        val = float(val)
        return val if np.isfinite(val) else None

    def _iter_xs(self, result: RootResult, method: str) -> list[float]:
        """Все x-приближения из шагов плюс найденный корень — для диапазона."""
        xs = []
        for step in result.steps or []:
            x = self._step_x(step, method)
            if x is not None:
                xs.append(x)
        if result.x_root is not None and np.isfinite(result.x_root):
            xs.append(float(result.x_root))
        return xs

    def _plot(self, result: RootResult, method: str) -> None:
        """Кривая f(x), линия y=0, точки итераций с номерами и звезда-корень."""
        if self.func is None:
            return
        self.ax.clear()

        xs = self._iter_xs(result, method)
        if xs:
            lo, hi = min(xs), max(xs)
            pad = max((hi - lo) * 0.35, 1.0)  # поля вокруг итераций
            lo, hi = lo - pad, hi + pad
        else:
            lo, hi = -5.0, 5.0

        # Если функция содержит ln — держим область строго x>0.
        if "ln" in self.func.text.lower() and lo <= 0:
            lo = 1e-3
            if hi <= lo:
                hi = lo + 5.0

        grid = np.linspace(lo, hi, 600)
        gx, ys = [], []
        for x in grid:
            y = self._safe_eval(self.func.f, x)
            if y is not None:
                gx.append(x)
                ys.append(y)
        if gx:
            self.ax.plot(gx, ys, "-", color="#1f77b4", lw=1.8, label="f(x)")
        # Ось y=0: корень — это пересечение графика с ней.
        self.ax.axhline(0.0, color="gray", lw=1.0, ls="--", alpha=0.7)

        # Точки итераций с подписями-номерами.
        for step in result.steps or []:
            xv = self._step_x(step, method)
            if xv is None:
                continue
            yv = self._safe_eval(self.func.f, xv)
            if yv is None:
                continue
            self.ax.plot([xv], [yv], "o", color="#ff7f0e", ms=6, zorder=5)
            n = step.get("n")
            if n is not None:
                self.ax.annotate(
                    str(n), (xv, yv), textcoords="offset points",
                    xytext=(4, 6), fontsize=8,
                )

        # Найденный корень — крупная звезда (на оси y=0).
        if result.x_root is not None:
            ym = self._safe_eval(self.func.f, result.x_root)
            if ym is None and result.f_root is not None:
                ym = float(result.f_root)
            if ym is not None:
                self.ax.plot(
                    [float(result.x_root)], [ym], "*", color="crimson", ms=18,
                    zorder=6, label="корень",
                )

        self.ax.set_title(
            "График f(x): корень методом "
            + ("Ньютона" if method == "newton" else "секущих")
        )
        self.ax.set_xlabel("x")
        self.ax.set_ylabel("f(x)")
        self.ax.grid(True, alpha=0.3)
        self.ax.legend(loc="best", fontsize=9)
        self.figure.tight_layout()
        self.canvas.draw_idle()


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Доп. подсказка Qt о каталоге плагинов (важно на Windows).
    try:
        import PyQt5

        base = os.path.dirname(PyQt5.__file__)
        for sub in ("Qt5", "Qt"):
            plugins = os.path.join(base, sub, "plugins")
            if os.path.isdir(plugins):
                app.addLibraryPath(plugins)
                break
    except Exception:
        pass

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
