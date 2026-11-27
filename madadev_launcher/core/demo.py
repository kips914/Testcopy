# -*- coding: utf-8 -*-
"""Демо-репозиторий-заглушка (по умолчанию ВЫКЛЮЧЕН).

Генерирует ~150 пакетов-заглушек: карты (маршруты), сценарии к ним, моды
подвижного состава, дополнения и готовые наборы — исключительно для
проверки интерфейса и пайплайна лаунчера, НЕ для игры. Реальный контент
устанавливается из архивов/папок или подключается как зеркало
(см. README, tools/make_repo.py).

Включается вручную: Настройки → «Демо-каталог-заглушка».
Каждая карта при установке автоматически подтягивает свои сценарии,
звуки и погоду — все возможности «авто-дополнений» на больших данных.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Карты (маршруты): (id, папка в ROUTES/, полное название, короткое название)
# ---------------------------------------------------------------------------
_ROUTES = [
    ("route-red-square", "RedSquare", "Красная площадь (демо)", "Красная площадь"),
    ("route-kiyevsky", "Kiyevsky", "Киевский ход — Москва–Сухиничи", "Киевский ход"),
    ("route-chernyshevsk", "Chernyshevsk", "Чернышевск — Нижневолжск", "Чернышевск"),
    ("route-pavlovsk", "Pavlovsk", "Павловск", "Павловск"),
    ("route-novokuznetsk", "Novokuznetsk", "Новокузнецк — Прокопьевск", "Новокузнецк"),
    ("route-uspensk", "Uspensk", "Успенск", "Успенск"),
    ("route-tula", "Tula", "Тула — Сухиничи", "Тула"),
    ("route-smolensk", "Smolensk", "Смоленск — Вязьма", "Смоленск"),
    ("route-yaroslavl", "Yaroslavl", "Ярославль — Рыбинск", "Ярославль"),
    ("route-vologda", "Vologda", "Вологда — Череповец", "Вологда"),
    ("route-kostroma", "Kostroma", "Кострома — Шарья", "Кострома"),
    ("route-kaliningrad", "Kaliningrad", "Калининград — Светлогорск", "Калининград"),
    ("route-sochi", "Sochi", "Сочи — Адлер", "Сочи"),
    ("route-kmv", "Kmv", "Кавказские Минеральные Воды — Пятигорск", "КМВ"),
    ("route-kislovodsk", "Kislovodsk", "Ессентуки — Кисловодск", "Кисловодск"),
    ("route-krasnoyarsk", "Krasnoyarsk", "Красноярск — Абакан", "Красноярск"),
    ("route-irkutsk", "Irkutsk", "Иркутск — Ангарск", "Иркутск"),
    ("route-ulan-ude", "UlanUde", "Улан-Удэ — Селенгинск", "Улан-Удэ"),
    ("route-khabarovsk", "Khabarovsk", "Хабаровск — Комсомольск", "Хабаровск"),
    ("route-vladivostok", "Vladivostok", "Владивосток — Уссурийск", "Владивосток"),
    ("route-omsk", "Omsk", "Омск — Новосибирск", "Омск"),
    ("route-tyumen", "Tyumen", "Тюмень — Омск", "Тюмень"),
    ("route-yekaterinburg", "Yekaterinburg", "Екатеринбург — Каменск-Уральский",
     "Екатеринбург"),
    ("route-perm", "Perm", "Пермь — Кунгур", "Пермь"),
    ("route-kazan", "Kazan", "Казань — Нижнекамск", "Казань"),
    ("route-samara", "Samara", "Самара — Сызрань", "Самара"),
    ("route-orenburg", "Orenburg", "Оренбург — Орск", "Оренбург"),
    ("route-ufa", "Ufa", "Уфа — Салават", "Уфа"),
    ("route-murmansk", "Murmansk", "Мурман — Кировск", "Мурман"),
    ("route-vorkuta", "Vorkuta", "Воркута — Усинск", "Воркута"),
]

# Названия сценариев — по кругу, чтобы у разных маршрутов отличались
_SCEN_NAMES = [
    "Утренняя электричка",
    "Грузовой рейс",
    "Ночной экспресс",
    "Снегоуборочный участок",
    "Служебный спецрейс",
]
_SCEN_PER_ROUTE = 3

# ---------------------------------------------------------------------------
# Моды подвижного состава: (id, код в TRAINSET, короткое название, имя или None)
# ---------------------------------------------------------------------------
_TRAINS = [
    ("mod-train-ep20", "EP20", "ЭП20 «Орлан»", "Мод: ЭП20 (демо)"),
    ("mod-train-chs7", "Chs7", "ЧС7", None),
    ("mod-train-chs4t", "Chs4T", "ЧС4Т", None),
    ("mod-train-3es4k", "3Es4K", "3ЭС4К", None),
    ("mod-train-2es4k", "2Es4K", "2ЭС4К", None),
    ("mod-train-tep70bs", "Tep70BS", "ТЭП70БС", None),
    ("mod-train-es2p", "Es2P", "ЭС2П «Аллегро»", None),
    ("mod-train-ed9m", "Ed9M", "ЭД9М", None),
    ("mod-train-lastochka", "Lastochka", "Ласточка (ЭС1П)", None),
    ("mod-train-sapsan", "Sapsan", "Сапсан", None),
    ("mod-train-vl80", "Vl80", "ВЛ80С", None),
    ("mod-train-vl10", "Vl10", "ВЛ10", None),
    ("mod-train-2es5k", "2Es5K", "2ЭС5К «Ермак»", None),
    ("mod-train-tem18", "Tem18", "ТЭМ18", None),
    ("mod-train-2m62u", "2M62U", "2М62У", None),
    ("mod-train-tgm4", "Tgm4", "ТГМ4", None),
    ("mod-train-tu6a", "Tu6A", "ТУ6А", None),
]

# ---------------------------------------------------------------------------
# Дополнения: (id, имя, файлы, зависит от, описание)
# ---------------------------------------------------------------------------
_ADDONS = [
    ("addon-sound-demo",
     "Дополнение: Звуки (демо)",
     {"GLOBAL/SOUNDS/madadev_demo.txt": "Демо-звуковые файлы.\n"},
     ["base-assets"],
     "Звуковое дополнение. Подтягивается автоматически к картам."),
    ("addon-cabine-demo",
     "Дополнение: Кабина (демо)",
     {"TRAINS/TRAINSET/EP20/cabine_demo.txt": "Демо-кабина машиниста.\n"},
     ["base-assets"],
     "Кабинное дополнение ЭП20. Подтягивается автоматически к моду ЭП20."),
    ("addon-weather-rain",
     "Дополнение: Дождь и гроза",
     {"GLOBAL/WEATHER/rain.txt": "Демо-погода: дождь и гроза.\n"},
     ["base-assets"],
     "Погодное дополнение. Подтягивается автоматически к картам."),
    ("addon-weather-snow",
     "Дополнение: Снегопад",
     {"GLOBAL/WEATHER/snow.txt": "Демо-погода: снегопад.\n"},
     ["base-assets"],
     "Погодное дополнение. Подтягивается автоматически к картам."),
    ("addon-sound-horn",
     "Дополнение: Гудки и стрелки",
     {"GLOBAL/SOUNDS/horn_pack.txt": "Демо-звуки гудков и стрелочных переводов.\n"},
     ["base-assets"],
     "Звуковой пакет: гудки, стрелки, переезды."),
    ("addon-ui-hud",
     "Дополнение: Интерфейс машиниста",
     {"GLOBAL/UI/hud.txt": "Демо-интерфейс: скоростомер, сигналы, тормоза.\n"},
     ["base-assets"],
     "Интерфейсное дополнение (HUD кабины)."),
    ("addon-light-night",
     "Дополнение: Ночное освещение",
     {"GLOBAL/LIGHTS/night.txt": "Демо-ночное освещение станций и путей.\n"},
     ["base-assets"],
     "Освещение: фонари станций, светофоры, кабины ночью."),
    ("addon-vagon-pack",
     "Дополнение: Пакет вагонов",
     {"TRAINS/TRAINSET/WagonsPack/readme.txt": "Демо-пакет пассажирских вагонов.\n"},
     ["base-assets"],
     "Вагоны: плацкарт, купе, ресторан, почтово-багажный."),
    ("addon-signal-pack",
     "Дополнение: Светофоры и сигнализация",
     {"GLOBAL/SIGNALS/signals.txt": "Демо-светофоры, автоблокировка, МПЦ.\n"},
     ["base-assets"],
     "Сигнализация: светофоры, автоблокировка, табло станций."),
]

_BUNDLE_FILES = {
    "bundle-routes": ".mdl_bundle_routes.txt",
    "bundle-scenarios": ".mdl_bundle_scenarios.txt",
    "bundle-mods": ".mdl_bundle_mods.txt",
    "bundle-addons": ".mdl_bundle_addons.txt",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Сборка спецификаций пакетов
# ---------------------------------------------------------------------------
def build_specs() -> list:
    """Полный список спецификаций пакетов каталога (в порядке манифеста)."""
    specs: list = []

    # 1. База
    specs.append({
        "id": "base-assets",
        "name": "Базовые ассеты RTS",
        "type": "base",
        "version": "1.0.0",
        "description": "Системные файлы симулятора, нужны всем картам, "
                       "сценариям и модам.",
        "depends": [],
        "addons": [],
        "files": {
            "GLOBAL/madadev_demo/README.txt": (
                "Базовые ассеты MaDaDev RTS (демо-репозиторий лаунчера).\n"
                "Сюда же раскладываются системные файлы из обычных пакетов.\n"
            ),
            "TRAINS/TRAINSET/_demo/readme.txt": "Демо-набор подвижного состава.\n",
        },
    })

    # 2. Карты + их сценарии
    scenario_ids_all: list = []
    route_ids: list = []
    for ridx, (rid, folder, title, short) in enumerate(_ROUTES):
        route_ids.append(rid)
        weather = "addon-weather-rain" if ridx % 2 == 0 else "addon-weather-snow"

        # Сценарии маршрута
        scen_specs = []
        if rid == "route-red-square":
            # Первый сценарий — исходный, как в первом демо-каталоге
            scen_specs.append({
                "id": "scenario-red-square-1",
                "name": "Сценарий: Утренний рейс (демо)",
                "type": "scenario",
                "version": "1.0.0",
                "description": "Демо-сценарий для карты «Красная площадь». "
                               "Ставится автоматически вместе с картой.",
                "depends": [rid],
                "addons": [],
                "files": {
                    "ROUTES/RedSquare/ACTIVITIES/morning_run.txt": (
                        "[activity]\n"
                        "Name=Утренний рейс\n"
                        "Desc=Демо-сценарий, проверка установки через лаунчер\n"
                    ),
                },
            })
            start = 1
        else:
            start = 0
        for k in range(start, _SCEN_PER_ROUTE):
            sc_name = _SCEN_NAMES[(ridx + k) % len(_SCEN_NAMES)]
            sc_id = f"scenario-{rid.removeprefix('route-')}-{k + 1}"
            scen_specs.append({
                "id": sc_id,
                "name": f"Сценарий: {sc_name} — {short}",
                "type": "scenario",
                "version": "1.0.0",
                "description": f"Сценарий для карты «{short}». "
                               "Ставится автоматически вместе с картой.",
                "depends": [rid],
                "addons": [],
                "files": {
                    f"ROUTES/{folder}/ACTIVITIES/{sc_id}.txt": (
                        f"[activity]\nName={sc_name}\nRoute={short}\n"
                        f"Desc=Демо-сценарий, проверка установки через лаунчер\n"
                    ),
                },
            })
        scenario_ids_all.extend(s["id"] for s in scen_specs)

        # Карта: подтягивает свои сценарии + звуки + погоду
        if rid == "route-red-square":
            route_name = "Карта: Красная площадь (демо)"
            route_version = "1.2.0"
            route_description = ("Демо-маршрут. При установке автоматически "
                                 "подтягивает сценарий и звуковое дополнение.")
            route_files = {
                "ROUTES/RedSquare/routes.txt": (
                    "; Демо-маршрут MaDaDev RTS\n"
                    "[route]\n"
                    "Name=Красная площадь\n"
                    "Desc=Демонстрационный маршрут для проверки лаунчера\n"
                ),
                "ROUTES/RedSquare/path.dat": "demo-path-data\n",
                "ROUTES/RedSquare/geo/terras.dat": "demo-geo-data\n",
            }
        else:
            route_name = f"Карта: {title}"
            route_version = "1.0.0"
            route_description = (f"Демо-маршрут «{short}». При установке "
                                 "автоматически подтягивает сценарии, звуки "
                                 "и погоду.")
            route_files = {
                f"ROUTES/{folder}/routes.txt": (
                    f"; Демо-маршрут MaDaDev RTS\n[route]\n"
                    f"Name={title}\nDesc=Демонстрационный маршрут\n"
                ),
                f"ROUTES/{folder}/path.dat": "demo-path-data\n",
                f"ROUTES/{folder}/geo/terras.dat": "demo-geo-data\n",
            }

        route_spec = {
            "id": rid,
            "name": route_name,
            "type": "map",
            "version": route_version,
            "description": route_description,
            "depends": ["base-assets"],
            "addons": [s["id"] for s in scen_specs]
                      + ["addon-sound-demo", weather],
            "files": route_files,
        }
        specs.append(route_spec)
        specs.extend(scen_specs)

    # 3. Моды подвижного состава
    train_ids: list = []
    for tid, code, short, override_name in _TRAINS:
        train_ids.append(tid)
        addons = (["addon-cabine-demo"] if tid == "mod-train-ep20"
                  else ["addon-cabine-pack"])
        if tid == "mod-train-ep20":
            name = "Мод: ЭП20 (демо)"
            version = "1.1.0"
            description = ("Демо-мод подвижного состава. При установке "
                           "подтягивает кабинное дополнение.")
            files = {
                "TRAINS/TRAINSET/EP20/ep20_demo.txt": "Демо-мод ЭП20 (имитация модели).\n",
                "TRAINS/CONSISTS/ep20_demo.con": "; Демо-состав ЭП20\n",
            }
        else:
            name = override_name or f"Мод: {short}"
            version = "1.0.0"
            description = (f"Демо-мод подвижного состава {short}. При установке "
                           "подтягивает кабинный пакет.")
            files = {
                f"TRAINS/TRAINSET/{code}/readme.txt": f"Демо-мод {short}.\n",
                f"TRAINS/CONSISTS/{tid}.con": f"; Демо-состав {short}\n",
            }
        specs.append({
            "id": tid,
            "name": name,
            "type": "mod",
            "version": version,
            "description": description,
            "depends": ["base-assets"],
            "addons": addons,
            "files": files,
        })

    # 4. Дополнения
    addon_ids: list = []
    for aid, name, files, depends, description in _ADDONS:
        addon_ids.append(aid)
        specs.append({
            "id": aid,
            "name": name,
            "type": "addon",
            "version": "1.0.0",
            "description": description,
            "depends": list(depends),
            "addons": [],
            "files": dict(files),
        })
    # Кабинный пакет для остальных модов (у ЭП20 — свой)
    addon_ids.append("addon-cabine-pack")
    specs.append({
        "id": "addon-cabine-pack",
        "name": "Дополнение: Кабинный пакет",
        "type": "addon",
        "version": "1.0.0",
        "description": "Кабины машиниста для модов. Подтягивается автоматически "
                       "к модам подвижного состава.",
        "depends": ["base-assets"],
        "addons": [],
        "files": {
            "TRAINS/TRAINSET/CabinePack/readme.txt":
                "Демо-кабинный пакет для модов.\n",
        },
    })

    # 5. Наборы
    specs.append({
        "id": "bundle-routes",
        "name": f"Набор: Все карты ({len(route_ids)})",
        "type": "bundle",
        "version": "1.0.0",
        "description": "Ставит все карты каталога вместе с их сценариями, "
                       "звуками и погодой.",
        "depends": list(route_ids),
        "addons": [],
        "files": {_BUNDLE_FILES["bundle-routes"]:
                  "Набор всех карт установлен через лаунчер.\n"},
    })
    specs.append({
        "id": "bundle-scenarios",
        "name": f"Набор: Все сценарии ({len(scenario_ids_all)})",
        "type": "bundle",
        "version": "1.0.0",
        "description": "Ставит все сценарии каталога (и их карты).",
        "depends": list(scenario_ids_all),
        "addons": [],
        "files": {_BUNDLE_FILES["bundle-scenarios"]:
                  "Набор всех сценариев установлен через лаунчер.\n"},
    })
    specs.append({
        "id": "bundle-mods",
        "name": f"Набор: Все моды ({len(train_ids)})",
        "type": "bundle",
        "version": "1.0.0",
        "description": "Ставит все моды подвижного состава с кабинами.",
        "depends": list(train_ids),
        "addons": [],
        "files": {_BUNDLE_FILES["bundle-mods"]:
                  "Набор всех модов установлен через лаунчер.\n"},
    })
    specs.append({
        "id": "bundle-addons",
        "name": f"Набор: Все дополнения ({len(addon_ids)})",
        "type": "bundle",
        "version": "1.0.0",
        "description": "Ставит все дополнения каталога: звуки, погоду, "
                       "интерфейс, светофоры, вагоны.",
        "depends": list(addon_ids),
        "addons": [],
        "files": {_BUNDLE_FILES["bundle-addons"]:
                  "Набор всех дополнений установлен через лаунчер.\n"},
    })
    specs.append({
        "id": "bundle-full",
        "name": "Полная сборка (все пакеты)",
        "type": "bundle",
        "version": "1.0.0",
        "description": "Ставит весь каталог: все карты, сценарии, моды "
                       "и дополнения одним нажатием.",
        "depends": ["bundle-routes", "bundle-scenarios", "bundle-mods",
                    "bundle-addons"],
        "addons": [],
        "files": {
            ".mddl/bundle_info.txt": (
                "Полная сборка демо-каталога установлена через лаунчер "
                "MaDaDev RTS.\n"
            ),
        },
    })

    return specs


def build_demo_repo(root: str) -> str:
    """Создать демо-репозиторий в папке ``root``. Возвращает путь к manifest.json."""
    root = os.path.abspath(root)
    packages_dir = os.path.join(root, "packages")
    os.makedirs(packages_dir, exist_ok=True)

    entries = []
    for spec in build_specs():
        arcname = f"packages/{spec['id']}-{spec['version']}.zip"
        zip_path = os.path.join(root, *arcname.split("/"))
        # Пишем архив заново — всегда свежий и с гарантированным содержимым.
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for rel, content in spec["files"].items():
                zf.writestr(rel, content)
        with open(zip_path, "rb") as f:
            data = f.read()
        entries.append({
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
        })

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
