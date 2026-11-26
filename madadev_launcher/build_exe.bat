@echo off
chcp 65001 >nul 2>nul
title Сборка exe - MaDaDev RTS Launcher
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python не найден. Установи Python 3.11+ с python.org.
    pause
    exit /b 1
)

echo [1/2] Устанавливаю PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err

echo [2/2] Собираю standalone exe (это занимает 1-3 минуты)...
python -m PyInstaller --noconfirm --clean --onefile --noconsole ^
    --name MaDaDevRTS-Launcher ^
    --paths . ^
    --icon assets\launcher.ico ^
    --version-file version_info.txt ^
    --add-data "assets\launcher.png;." ^
    --dist-dir dist --workpath build --specpath build ^
    main.py
if errorlevel 1 goto :err

echo.
echo Готово: %~dp0dist\MaDaDevRTS-Launcher.exe
echo Файл самодостаточный: его можно раздать друзьям без Python.
pause
exit /b 0

:err
echo.
echo ОШИБКА СБОРКИ - смотри сообщения выше.
pause
exit /b 1
