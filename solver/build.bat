@echo off
REM ============================================================================
REM build.bat — сборка solver.exe для Windows с помощью PyInstaller.
REM
REM ВАЖНО:
REM   * запускать из папки solver, путь к которой БЕЗ кириллицы
REM     (например C:\Users\Имя\Desktop\solver — где solver латиницей);
REM   * .exe для Windows собирается только НА Windows;
REM   * готовый файл появится в dist\solver.exe и запускается на любом
REM     64-битном Windows без установленного Python.
REM ============================================================================
chcp 65001 >nul
setlocal

REM --- 1) виртуальное окружение и зависимости -------------------------------
py -3.12 -m venv venv
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

REM --- 2) сборка одного самодостаточного exe без окна консоли ---------------
REM --collect-data/-submodules matplotlib подстраховывают от пропуска данных
REM matplotlib (бэкенды, шрифты) в редких конфигурациях.
pyinstaller --onefile --windowed --name solver ^
    --collect-submodules matplotlib ^
    --collect-data matplotlib ^
    main.py

echo.
echo ============================================================
echo Готово. Запускаемый файл: dist\solver.exe
echo ============================================================
pause
endlocal
