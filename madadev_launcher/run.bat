@echo off
chcp 65001 >nul 2>nul
title MaDaDev RTS - Launcher
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python не найден.
    echo Установи Python 3.11+ с python.org и поставь галочку "Add python.exe to PATH".
    pause
    exit /b 1
)

python "%~dp0main.py"
if errorlevel 1 (
    echo.
    echo Лаунчер завершился с ошибкой. Покажи это окно при проблемах.
    pause
)
