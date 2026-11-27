# -*- coding: utf-8 -*-
"""Пути приложения: работают и из исходников, и из собранного .exe.

PyInstaller в режиме onefile распаковывает ресурсы во временный каталог
``sys._MEIPASS``, который удаляется после закрытия. Поэтому настройки
(``config.json``), демо-репозиторий и лог ошибок должны лежать **рядом с
exe**, а не внутри него — отсюда разделение ``app_dir()`` и
``resource_dir()``.
"""

from __future__ import annotations

import os
import sys

APP_NAME = "MaDaDevRTS-Launcher"


def is_frozen() -> bool:
    """True, если приложение запущено из собранного exe."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Папка с exe (или с исходниками) — сюда пишем данные пользователя."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    # core/paths.py -> core/ -> папка проекта
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir() -> str:
    """Папка с ресурсами: вшитые в exe (``_MEIPASS``) либо исходники."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", app_dir())
    return app_dir()
