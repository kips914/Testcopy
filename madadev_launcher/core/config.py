# -*- coding: utf-8 -*-
"""Настройки лаунчера (JSON-файл рядом с программой)."""

from __future__ import annotations

import json
import os

DEFAULTS = {
    # Папка с игрой (куда раскладываются ROUTES, TRAINS, GLOBAL…)
    "game_dir": "",
    # Исполняемый файл игры (пусто — определить автоматически)
    "game_exe": "",
    # Дополнительные зеркала репозитория (URL или путь к папке с manifest.json)
    "mirrors": [],
    # Индекс активного зеркала в общем списке (демо-зеркало идёт первым)
    "active_mirror": 0,
    # Встроенный демо-репозиторий-заглушка (только для проверки лаунчера,
    # НЕ для игры). По умолчанию выключен — в продукте только реальный
    # контент из зеркала, архивов и папок.
    "use_demo_repo": False,
    # Автоматически подтягивать дополнения пакетов
    "auto_addons": True,
    # Таймаут сетевых операций, сек
    "timeout": 30,
    # Геометрия окна
    "window_geometry": "1080x680",
}


# Публичный репозиторий РЕАЛЬНОГО контента (ветка `content` этого же
# репозитория, отдаётся с raw.githubusercontent.com): маршруты, составы,
# сценарии, база — собраны из открытых источников (см. README).
# Подключается в список зеркал автоматически — каталог не пустой с первого
# запуска, без демо-заглушек.
CONTENT_MIRROR = "https://raw.githubusercontent.com/kips914/Testcopy/content"


class Config:
    """Простое хранилище настроек с безопасным чтением/записью."""

    def __init__(self, path: str):
        self.path = path
        self.data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for key, value in loaded.items():
                    if key in DEFAULTS:
                        self.data[key] = value
        except FileNotFoundError:
            pass
        except Exception:
            # Повреждённый файл настроек — не роняем лаунчер, берём дефолты
            pass

    def save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get(self, key: str, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self.data[key] = value
