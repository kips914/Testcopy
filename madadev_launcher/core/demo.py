# -*- coding: utf-8 -*-
"""Встроенный демо-репозиторий.

Небольшой офлайн-каталог (карта + сценарий + мод + дополнение + полный
набор), чтобы лаунчер работал сразу, без внешних серверов. Пакеты
демонстрируют все возможности: зависимости и автоматическое подтягивание
дополнений.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone

# Каждый пакет: описание + файлы "путь/в/архиве" -> содержимое.
_PACKAGES = [
    {
        "id": "base-assets",
        "name": "Базовые ассеты RTS",
        "type": "base",
        "version": "1.0.0",
        "description": "Системные файлы симулятора, нужны всем картам, сценариям и модам.",
        "depends": [],
        "addons": [],
        "files": {
            "GLOBAL/madadev_demo/README.txt": (
                "Базовые ассеты MaDaDev RTS (демо-репозиторий лаунчера).\n"
                "Сюда же раскладываются системные файлы из обычных пакетов.\n"
            ),
            "TRAINS/TRAINSET/_demo/readme.txt": "Демо-набор подвижного состава.\n",
        },
    },
    {
        "id": "route-red-square",
        "name": "Карта: Красная площадь (демо)",
        "type": "map",
        "version": "1.2.0",
        "description": "Демо-маршрут. При установке автоматически подтягивает сценарий и звуковое дополнение.",
        "depends": ["base-assets"],
        "addons": ["scenario-red-square-1", "addon-sound-demo"],
        "files": {
            "ROUTES/RedSquare/routes.txt": (
                "; Демо-маршрут MaDaDev RTS\n"
                "[route]\n"
                "Name=Красная площадь\n"
                "Desc=Демонстрационный маршрут для проверки лаунчера\n"
            ),
            "ROUTES/RedSquare/path.dat": "demo-path-data\n",
            "ROUTES/RedSquare/geo/terras.dat": "demo-geo-data\n",
        },
    },
    {
        "id": "scenario-red-square-1",
        "name": "Сценарий: Утренний рейс (демо)",
        "type": "scenario",
        "version": "1.0.0",
        "description": "Демо-сценарий для карты «Красная площадь». Ставится автоматически вместе с картой.",
        "depends": ["route-red-square"],
        "addons": [],
        "files": {
            "ROUTES/RedSquare/ACTIVITIES/morning_run.txt": (
                "[activity]\n"
                "Name=Утренний рейс\n"
                "Desc=Демо-сценарий, проверка установки через лаунчер\n"
            ),
        },
    },
    {
        "id": "mod-train-ep20",
        "name": "Мод: ЭП20 (демо)",
        "type": "mod",
        "version": "1.1.0",
        "description": "Демо-мод подвижного состава. При установке подтягивает кабинное дополнение.",
        "depends": ["base-assets"],
        "addons": ["addon-cabine-demo"],
        "files": {
            "TRAINS/TRAINSET/EP20/ep20_demo.txt": "Демо-мод ЭП20 (имитация модели).\n",
            "TRAINS/CONSISTS/ep20_demo.con": "; Демо-состав ЭП20\n",
        },
    },
    {
        "id": "addon-sound-demo",
        "name": "Дополнение: Звуки (демо)",
        "type": "addon",
        "version": "1.0.0",
        "description": "Звуковое дополнение. Подтягивается автоматически к карте.",
        "depends": ["base-assets"],
        "addons": [],
        "files": {
            "GLOBAL/SOUNDS/madadev_demo.txt": "Демо-звуковые файлы.\n",
        },
    },
    {
        "id": "addon-cabine-demo",
        "name": "Дополнение: Кабина (демо)",
        "type": "addon",
        "version": "1.0.0",
        "description": "Кабинное дополнение. Подтягивается автоматически к моду ЭП20.",
        "depends": ["base-assets"],
        "addons": [],
        "files": {
            "TRAINS/TRAINSET/EP20/cabine_demo.txt": "Демо-кабина машиниста.\n",
        },
    },
    {
        "id": "bundle-full",
        "name": "Полная сборка (все пакеты)",
        "type": "bundle",
        "version": "1.0.0",
        "description": "Ставит все карты, сценарии, моды и дополнения демо-каталога одним нажатием.",
        "depends": [
            "route-red-square",
            "mod-train-ep20",
            "addon-sound-demo",
            "addon-cabine-demo",
        ],
        "addons": [],
        "files": {
            ".mddl/bundle_info.txt": (
                "Полная сборка демо-каталога установлена через лаунчер MaDaDev RTS.\n"
            ),
        },
    },
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_demo_repo(root: str) -> str:
    """Создать демо-репозиторий в папке ``root``. Возвращает путь к manifest.json."""
    root = os.path.abspath(root)
    packages_dir = os.path.join(root, "packages")
    os.makedirs(packages_dir, exist_ok=True)

    entries = []
    for spec in _PACKAGES:
        arcname = f"packages/{spec['id']}-{spec['version']}.zip"
        zip_path = os.path.join(root, *arcname.split("/"))
        # Пишем архив заново — всегда свежий и с гарантированным содержимым.
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for rel, content in spec["files"].items():
                zf.writestr(rel, content)
        with open(zip_path, "rb") as f:
            data = f.read()
        entries.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "type": spec["type"],
                "version": spec["version"],
                "description": spec["description"],
                "depends": list(spec["depends"]),
                "addons": list(spec["addons"]),
                "file": arcname,
                "size": len(data),
                "sha256": _sha256(data),
            }
        )

    manifest = {
        "schema": 1,
        "name": "Демо-репозиторий MaDaDev RTS",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "packages": entries,
    }
    manifest_path = os.path.join(root, "manifest.json")
    tmp = manifest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, manifest_path)
    return manifest_path


def ensure_demo_repo(root: str) -> str:
    """Создать демо-репозиторий, если его ещё нет. Возвращает папку."""
    root = os.path.abspath(root)
    if os.path.isfile(os.path.join(root, "manifest.json")):
        return root
    build_demo_repo(root)
    return root
