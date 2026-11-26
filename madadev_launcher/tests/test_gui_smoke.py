# -*- coding: utf-8 -*-
"""Headless smoke-тест GUI лаунчера на заглушке tkinter.

Прогоняет LauncherApp целиком: загрузка каталога, фильтры, установка
с авто-подтягиванием дополнений, удаление, авто-дополнения выключены,
ошибочное зеркало, запуск игры, закрытие.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(TESTS_DIR)
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, BASE)

import fake_tkinter as ftk  # noqa: E402

tk = ftk.install()

import main as launcher  # noqa: E402  (импортирует tkinter — уже заглушка)
from core.manifest import resolve  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    if cond:
        print(f"  ok  {name}")
    else:
        FAILS.append(name)
        print(f"FAIL  {name} {extra}")


def pump(app, predicate, timeout=15.0):
    """Крутить цикл сообщений, пока predicate не выполнится."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app._poll()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def log_errors(app):
    return [t for t, tags in app.log_text.content
            if "err" in tags]


def main_test():
    root = tk.Tk()
    app = launcher.LauncherApp(root)

    # 1. Каталог загрузился из демо-репозитория
    check("каталог загружен",
          pump(app, lambda: app.manifest is not None))
    n_pkgs = len(app.manifest.packages)
    check("большой каталог (150+ пакетов)", n_pkgs >= 150, str(n_pkgs))
    check("дерево = манифест", len(app.cat_tree._rows) == n_pkgs,
          str(len(app.cat_tree._rows)))
    check("журнал без ошибок (старт)", log_errors(app) == [],
          str(log_errors(app)))

    # 2. Поиск и фильтр по типу
    app.search_var.set("эп20")
    app._render_catalog()
    check("поиск 'эп20' -> 1 пакет", len(app.cat_tree._rows) == 1,
          str(list(app.cat_tree._rows)))
    app.search_var.set("")
    app.type_var.set("Карты")
    app._render_catalog()
    n_maps = sum(1 for p in app.manifest.packages if p.type == "map")
    check("фильтр 'Карты' -> все карты",
          len(app.cat_tree._rows) == n_maps and n_maps >= 25,
          f"{len(app.cat_tree._rows)}/{n_maps}")
    app.type_var.set("Все типы")
    app._render_catalog()
    check("фильтр сброшен -> весь каталог",
          len(app.cat_tree._rows) == n_pkgs)

    # 3. Папка игры
    game = tempfile.mkdtemp(prefix="rts_game_")
    app.game_dir_var.set(game)
    app._save_settings()
    pump(app, lambda: True, timeout=0.3)
    check("installer готов", app.installer.ready)

    # 4. Установка карты: подтягиваются base + сценарий + звук
    app.cat_tree._selection = ["route-red-square"]
    app._install_selected()
    check("задача стартовала", app.job_running)
    check("установка завершилась",
          pump(app, lambda: not app.job_running and
               app.status_var.get().startswith("Готово")))
    for rel in ("ROUTES/RedSquare/routes.txt",
                "ROUTES/RedSquare/ACTIVITIES/morning_run.txt",
                "GLOBAL/SOUNDS/madadev_demo.txt",
                "GLOBAL/madadev_demo/README.txt"):
        check(f"файл есть: {rel}",
              os.path.isfile(os.path.join(game, *rel.split("/"))))
    exp_pkgs, exp_pulled, _ = resolve(app.manifest, ["route-red-square"],
                                      auto_addons=True)
    check("репозиторий: все пакеты карты (с дополнениями)",
          len(app.installer.installed()) == len(exp_pkgs),
          f"{len(app.installer.installed())}/{len(exp_pkgs)}")
    check("статус в каталоге обновлён",
          "Установлено" in str(app.cat_tree._rows.get(
              "route-red-square", {}).get("values", "")))
    check("журнал без ошибок (установка)", log_errors(app) == [],
          str(log_errors(app)))

    # 5. Удаление пакетов, связанных с картой
    app._refresh_installed()
    check("дерево установленных заполнено",
          len(app.inst_tree._rows) == len(exp_pkgs),
          f"{len(app.inst_tree._rows)}/{len(exp_pkgs)}")
    app.inst_tree._selection = ["route-red-square",
                                "scenario-red-square-1",
                                "addon-sound-demo"]
    app._uninstall_selected()
    check("удаление завершилось",
          pump(app, lambda: not app.job_running and
               app.status_var.get() == "Удаление завершено"))
    check("файлы карты удалены",
          not os.path.isfile(os.path.join(game, "ROUTES", "RedSquare",
                                           "routes.txt")))
    check("актив остался (base)",
          os.path.isfile(os.path.join(game, "GLOBAL", "madadev_demo",
                                       "README.txt")))

    # 6. Авто-дополнения ВЫКЛЮЧЕНЫ: карта ставится без сценария/звука
    app.auto_addons_var.set(False)
    app._toggle_auto_addons()
    app.cat_tree._selection = ["route-red-square"]
    app._install_selected()
    check("установка без авто-дополнений",
          pump(app, lambda: not app.job_running and
               app.status_var.get().startswith("Готово")))
    check("карта стоит", os.path.isfile(
        os.path.join(game, "ROUTES", "RedSquare", "routes.txt")))
    check("сценарий НЕ подтянут", not os.path.isfile(
        os.path.join(game, "ROUTES", "RedSquare", "ACTIVITIES",
                     "morning_run.txt")))

    # 7. Обратно ВКЛЮЧАЕМ и ставим всё
    app.auto_addons_var.set(True)
    app._toggle_auto_addons()
    app._install_all()
    check("установка всех пакетов",
          pump(app, lambda: not app.job_running and
               app.status_var.get().startswith("Готово")))
    check("весь каталог установлен",
          len(app.installer.installed()) == n_pkgs,
          f"{len(app.installer.installed())}/{n_pkgs}")
    check("сценарий подтянут", os.path.isfile(
        os.path.join(game, "ROUTES", "RedSquare", "ACTIVITIES",
                     "morning_run.txt")))
    check("кабина мода подтянута", os.path.isfile(
        os.path.join(game, "TRAINS", "TRAINSET", "EP20", "cabine_demo.txt")))

    # 8. Проверка обновлений (обновлений нет) и повторная установка
    app._check_updates()
    app._install_all()
    check("повтор: всё уже установлено",
          pump(app, lambda: not app.job_running and
               app.status_var.get() == "Всё уже установлено — обновлений нет"),
          app.status_var.get())

    # 9. Настройки: зеркала (без диалогов), кеш, авто-галочки
    app._activate_mirror()   # без выделения — no-op
    app._remove_mirror()     # без выделения — no-op
    app._add_mirror()        # диалог отменён (None) — no-op
    check("зеркала не сломаны", len(app.effective_mirrors()) >= 1)
    app._clear_cache()
    check("кеш очищен", log_errors(app) == [], str(log_errors(app)))

    # 10. Ошибочное зеркало: каталог недоступен, но всё не падает
    app.demo_var.set(False)
    app._toggle_demo()
    check("ошибка каталога обработана",
          pump(app, lambda: app.status_var.get() == "Каталог недоступен"))
    check("сообщение показано",
          any(c[0] == "showwarning" for c in ftk.messagebox_calls),
          str(ftk.messagebox_calls[-3:]))
    # обратно включаем демо
    app.demo_var.set(True)
    app._toggle_demo()
    check("каталог снова загружен",
          pump(app, lambda: app.status_var.get().startswith("Каталог:")))

    # 11. Запуск игры: подставляем .exe (не исполняемый — ошибка в messagebox,
    # главное — что не падает)
    exe_path = os.path.join(game, "RTS.exe")
    with open(exe_path, "wb") as f:
        f.write(b"MZ fake")
    ftk.messagebox_calls.clear()
    app.launch_game()
    check("запуск игры не роняет лаунчер",
          any(c[0] == "showerror" for c in ftk.messagebox_calls)
          or any("Запускаю" in t for t, _ in app.log_text.content),
          str(ftk.messagebox_calls))

    # 12. Состояние busy: кнопка отмены и сброс
    app._set_busy(True)
    check("кнопка отмены создаётся при busy", hasattr(app, "_cancel_btn"))
    app._set_busy(False)
    check("busy снят, отмена сброшена", not app.job_cancel.is_set())

    # 13. Закрытие
    app._on_close()
    check("окно закрыто", root.destroyed)
    check("настройки сохранились",
          os.path.isfile(os.path.join(BASE, "config.json")))

    # Ожидаемая ошибка из шага 10 — единственная в журнале
    errs = [t for t in log_errors(app) if "Каталог недоступен" not in t]
    check("журнал без неожиданных ошибок (финал)", errs == [], str(errs))

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} -> {FAILS}")
        return 1
    print("GUI SMOKE: ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
