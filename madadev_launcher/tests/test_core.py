# -*- coding: utf-8 -*-
"""Функциональное тестирование ядра лаунчера (без GUI)."""
import json
import os
import sys
import tempfile
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.config import Config
from core.demo import ensure_demo_repo, build_demo_repo
from core.install import (Installer, fmt_size, guess_package_type,
                          looks_like_game_tree, read_package_meta,
                          sanitize_package_id, version_cmp)
from core.manifest import load_manifest, resolve, ManifestError
from core.net import RepoClient, RepoError, sha256_file

fails = []


def check(name, cond, extra=""):
    if cond:
        print(f"  ok  {name}")
    else:
        fails.append(name)
        print(f"FAIL  {name} {extra}")


# 1. Демо-репозиторий
with tempfile.TemporaryDirectory() as tmp:
    repo = os.path.join(tmp, "repo")
    build_demo_repo(repo)
    check("demo manifest exists", os.path.isfile(os.path.join(repo, "manifest.json")))

    client = RepoClient([repo])
    manifest = load_manifest(client)
    n_pkgs = len(manifest.packages)
    check("большой каталог (150+ пакетов)", n_pkgs >= 150, f"got {n_pkgs}")
    check("manifest name", "Демо" in manifest.name)

    # 2. Зеркала: локальный путь и file:// URL
    client2 = RepoClient([f"file://{repo}"])
    m2 = load_manifest(client2)
    check("file:// mirror works", len(m2.packages) == n_pkgs)

    # фейловер: битое зеркало первым, рабочее вторым
    client3 = RepoClient([os.path.join(tmp, "nope"), repo])
    m3 = load_manifest(client3)
    check("mirror failover", len(m3.packages) == n_pkgs)

    # 3. Резолв зависимостей и дополнений
    packages, pulled, missing = resolve(manifest, ["route-red-square"],
                                        auto_addons=True)
    ids = [p.id for p in packages]
    check("route pulls base", "base-assets" in ids, str(ids))
    check("route pulls scenario addon", "scenario-red-square-1" in pulled, str(pulled))
    check("route pulls sound addon", "addon-sound-demo" in pulled, str(pulled))
    check("no missing", missing == [], str(missing))
    check("deps before dependents",
          ids.index("base-assets") < ids.index("route-red-square"), str(ids))
    check("route before scenario",
          ids.index("route-red-square") < ids.index("scenario-red-square-1"), str(ids))

    # без авто-дополнений: только зависимости
    packages2, pulled2, _ = resolve(manifest, ["route-red-square"],
                                    auto_addons=False)
    ids2 = [p.id for p in packages2]
    check("no auto addons -> only depends",
          ids2 == ["base-assets", "route-red-square"], str(ids2))

    # полная сборка: подтягиваются ВСЕ пакеты
    packages3, pulled3, _ = resolve(manifest, ["bundle-full"], auto_addons=True)
    ids3 = [p.id for p in packages3]
    all_ids = {p.id for p in manifest.packages}
    check("bundle-full покрывает весь каталог",
          set(ids3) == all_ids,
          f"{len(ids3)}/{len(all_ids)}")
    check("bundle order: deps first",
          ids3.index("route-red-square") < ids3.index("bundle-full"), str(ids3))

    # отсутствующий id
    _, _, missing4 = resolve(manifest, ["no-such-pkg"])
    check("missing id reported", missing4 == ["no-such-pkg"], str(missing4))

    # 4. Скачивание с проверкой sha256
    with tempfile.TemporaryDirectory() as tmp2:
        dest = os.path.join(tmp2, "file.zip")
        pkg = manifest.get("route-red-square")
        client.download(pkg.file, dest, sha256=pkg.sha256)
        check("download + sha256", os.path.isfile(dest)
              and sha256_file(dest) == pkg.sha256)

        # битая контрольная сумма -> ошибка
        try:
            client.download(pkg.file, dest + ".bad", sha256="0" * 64, max_tries=1)
            check("bad sha raises", False)
        except RepoError:
            check("bad sha raises", True)

        # прогресс и отмена
        seen = []
        client.download(pkg.file, dest + ".p", sha256=pkg.sha256,
                        progress=lambda d, t: seen.append((d, t)))
        check("progress callbacks", len(seen) > 0 and seen[-1][0] >= seen[0][0])

        from core.net import Cancelled
        try:
            client.download(pkg.file, dest + ".c", sha256=pkg.sha256,
                            cancel=lambda: True)
            check("cancel raises", False)
        except Cancelled:
            check("cancel raises", True)

        # 5. Установка в папку игры
        game = os.path.join(tmp2, "game")
        os.makedirs(game)
        inst = Installer(game)
        check("installer ready", inst.ready)

        # ставим всё (как «Установить всё»)
        order, pulled_all, _ = resolve(manifest, [p.id for p in manifest.packages],
                                       auto_addons=True)
        for p in order:
            zpath = inst.cache_path(p)
            os.makedirs(os.path.dirname(zpath), exist_ok=True)
            client.download(p.file, zpath, sha256=p.sha256)
            inst.install_package(p, zpath)

        expect_files = [
            "ROUTES/RedSquare/routes.txt",
            "ROUTES/RedSquare/ACTIVITIES/morning_run.txt",
            "TRAINS/TRAINSET/EP20/ep20_demo.txt",
            "TRAINS/TRAINSET/EP20/cabine_demo.txt",
            "GLOBAL/SOUNDS/madadev_demo.txt",
            "GLOBAL/madadev_demo/README.txt",
            ".mddl/bundle_info.txt",
        ]
        for rel in expect_files:
            check(f"file installed: {rel}", os.path.isfile(os.path.join(game, *rel.split("/"))))

        installed = inst.installed()
        check("registry == весь каталог", len(installed) == n_pkgs,
              f"{len(installed)}/{n_pkgs}")
        check("registry version", installed["route-red-square"]["version"] == "1.2.0")

        # статусы
        check("status installed", inst.status_label(manifest.get("route-red-square")) == "Установлено")

        # повторная установка — no-op по версии (пропускается в UI по status)
        check("status same version",
              inst.status(manifest.get("route-red-square")) == "installed")

        # обновление: подменяем версию в реестре на старую -> update
        state = inst._load_state()
        state["packages"]["route-red-square"]["version"] = "1.0.0"
        inst._save_state(state)
        check("status update",
              inst.status(manifest.get("route-red-square")) == "update")
        check("status label update",
              inst.status_label(manifest.get("route-red-square")) == "Есть обновление")

        # переустановка новой версии убирает старые файлы-призраки:
        # добавим файл, которого нет в новой версии
        ghost = os.path.join(game, "ROUTES", "RedSquare", "old_file.txt")
        with open(ghost, "w") as f:
            f.write("x")
        st = inst._load_state()
        st["packages"]["route-red-square"]["files"].append("ROUTES/RedSquare/old_file.txt")
        inst._save_state(st)
        inst.install_package(manifest.get("route-red-square"),
                             inst.cache_path(manifest.get("route-red-square")))
        check("old version ghost file removed", not os.path.exists(ghost))
        check("new version files present",
              os.path.isfile(os.path.join(game, "ROUTES", "RedSquare", "routes.txt")))
        check("status back to installed",
              inst.status(manifest.get("route-red-square")) == "installed")

        # удаление сценария
        check("uninstall scenario", inst.uninstall("scenario-red-square-1"))
        check("scenario file gone",
              not os.path.isfile(os.path.join(game, "ROUTES", "RedSquare",
                                               "ACTIVITIES", "morning_run.txt")))
        check("route file kept",
              os.path.isfile(os.path.join(game, "ROUTES", "RedSquare", "routes.txt")))
        check("uninstall unknown -> False", not inst.uninstall("nope"))

        # кеш
        check("cache detected", inst.is_cached(manifest.get("mod-train-ep20")))
        freed = inst.clear_cache()
        cache_left = (sum(os.path.getsize(os.path.join(inst.cache_dir, n))
                          for n in os.listdir(inst.cache_dir))
                      if os.path.isdir(inst.cache_dir) else 0)
        check("cache cleared", freed > 0 and cache_left == 0,
              f"freed={freed} left={cache_left}")

        # защита от zip-slip
        evil = os.path.join(tmp2, "evil.zip")
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../hacked.txt", "boom")
        try:
            inst.install_package(manifest.get("base-assets"), evil)
            check("zip-slip blocked", False)
        except RuntimeError:
            check("zip-slip blocked", True)
        check("no file outside game dir",
              not os.path.isfile(os.path.join(tmp2, "hacked.txt")))

# 6. Версии и размеры
check("version cmp", version_cmp("1.2.0", "1.10.0") < 0)
check("version cmp equal", version_cmp("1.2", "1.2.0") == 0)
check("fmt_size", fmt_size(2048) == "2.0 КБ", fmt_size(2048))

# 7. Конфиг
with tempfile.TemporaryDirectory() as tmp3:
    cfg_path = os.path.join(tmp3, "config.json")
    cfg = Config(cfg_path)
    cfg.set("game_dir", "D:/game")
    cfg.save()
    cfg2 = Config(cfg_path)
    check("config roundtrip", cfg2.get("game_dir") == "D:/game")
    # битый файл настроек
    with open(cfg_path, "w") as f:
        f.write("{broken")
    cfg3 = Config(cfg_path)
    check("broken config -> defaults", cfg3.get("game_dir") == "")

# 8. Битый манифест
with tempfile.TemporaryDirectory() as tmp4:
    with open(os.path.join(tmp4, "manifest.json"), "w") as f:
        f.write("{not json")
    try:
        load_manifest(RepoClient([tmp4]))
        check("broken manifest raises", False)
    except ManifestError:
        check("broken manifest raises", True)
    with open(os.path.join(tmp4, "manifest.json"), "w") as f:
        f.write('{"packages": []}')
    try:
        load_manifest(RepoClient([tmp4]))
        check("empty packages raises", False)
    except ManifestError:
        check("empty packages raises", True)

# 9. Реальная установка из архива/папки (без репозитория)
with tempfile.TemporaryDirectory() as tmp5:
    game = os.path.join(tmp5, "game")
    os.makedirs(game)
    inst = Installer(game)

    # Архив с mddl.json и настоящими бинарными файлами
    zp = os.path.join(tmp5, "RealRoute.zip")
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("mddl.json", json.dumps({
            "id": "Real Route!",
            "name": "Реальный маршрут",
            "type": "map",
            "version": "2.1.0",
            "depends": ["base-assets"],
            "addons": ["sound-x"],
        }, ensure_ascii=False))
        zf.writestr("ROUTES/RealRoute/routes.txt", "[route]\nName=Real\n")
        zf.writestr("TRAINS/TRAINSET/X/model.sd", b"\x00\x01\x02\x03")

    meta = read_package_meta(zp)
    check("meta из архива", meta.get("name") == "Реальный маршрут")
    entry = inst.install_local(zp, meta)
    check("id санитайзен", entry["id"] == "real-route", entry["id"])
    check("тип из meta", entry["type"] == "map")
    check("версия из meta", entry["version"] == "2.1.0")
    check("файл установлен",
          os.path.isfile(os.path.join(game, "ROUTES", "RealRoute",
                                       "routes.txt")))
    with open(os.path.join(game, "TRAINS", "TRAINSET", "X", "model.sd"),
              "rb") as f:
        check("бинарный файл цел", f.read() == b"\x00\x01\x02\x03")
    check("mddl.json не в игре",
          not os.path.isfile(os.path.join(game, "mddl.json")))
    check("запись в реестре",
          inst.installed().get("real-route", {}).get("version") == "2.1.0")
    check("source=archive",
          inst.installed()["real-route"].get("source") == "archive")

    # Переустановка другой версии убирает старые файлы
    zp2 = os.path.join(tmp5, "RealRoute_v2.zip")
    with zipfile.ZipFile(zp2, "w") as zf:
        zf.writestr("mddl.json", json.dumps({
            "id": "real-route", "version": "3.0.0"}))
        zf.writestr("ROUTES/RealRoute/routes.txt", "[route]\nName=Real v2\n")
    inst.install_local(zp2, read_package_meta(zp2))
    check("обновление локального пакета",
          inst.installed()["real-route"]["version"] == "3.0.0")
    check("старые файлы перезаписаны",
          os.path.isfile(os.path.join(game, "ROUTES", "RealRoute",
                                       "routes.txt")))

    # Папка без метаданных: id/тип выводятся автоматически
    fld = os.path.join(tmp5, "MyMod")
    os.makedirs(os.path.join(fld, "GLOBAL", "extra"))
    with open(os.path.join(fld, "GLOBAL", "extra", "x.txt"), "w") as f:
        f.write("x")
    e2 = inst.install_local(fld)
    check("папка: тип по структуре", e2["type"] == "addon", e2["type"])
    check("папка: source=folder", e2["source"] == "folder")
    check("папка установлена",
          os.path.isfile(os.path.join(game, "GLOBAL", "extra", "x.txt")))

    # Тип определяется по содержимому
    check("guess: scenario",
          guess_package_type(["ROUTES/R/ACTIVITIES/a.txt"]) == "scenario")
    check("guess: map",
          guess_package_type(["ROUTES/R/routes.txt"]) == "map")

    # База MaDaDev RTS = RTrainSim: ROUTES/TRAINS/GLOBAL/SOUND/GUI
    check("game tree: каталоги RTS",
          looks_like_game_tree(["SOUND", "GUI"])
          and looks_like_game_tree(["ROUTES"])
          and looks_like_game_tree(["ROUTES", "TRAINS", "GLOBAL", "SOUND"])
          and not looks_like_game_tree(["docs", "readme.txt"]))

    # Защита от zip-slip в локальной установке
    evil = os.path.join(tmp5, "evil_local.zip")
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../hack.txt", "x")
    try:
        inst.install_local(evil)
        check("local zip-slip blocked", False)
    except RuntimeError:
        check("local zip-slip blocked", True)
    check("нет файла вне игры",
          not os.path.isfile(os.path.join(tmp5, "hack.txt")))

    # Архив без файлов игры — отказ
    empty = os.path.join(tmp5, "empty.zip")
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("mddl.json", "{}")
    try:
        inst.install_local(empty)
        check("пустой архив отклонён", False)
    except RuntimeError:
        check("пустой архив отклонён", True)

    check("sanitize id",
          sanitize_package_id("My Cool Mod!") == "my-cool-mod",
          sanitize_package_id("My Cool Mod!"))

# 10. make_repo: папка с реальными пакетами -> репозиторий -> установка
from tools.make_repo import build_repo  # noqa: E402

with tempfile.TemporaryDirectory() as tmp6:
    src = os.path.join(tmp6, "mods")
    os.makedirs(src)

    # Пакет-папка (реальная структура карты)
    pkg = os.path.join(src, "cool_route")
    os.makedirs(os.path.join(pkg, "ROUTES", "CoolRoute"))
    with open(os.path.join(pkg, "ROUTES", "CoolRoute", "routes.txt"),
              "w") as f:
        f.write("[route]\nName=Cool\n")
    with open(os.path.join(pkg, "mddl.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "cool-route", "name": "Крутой маршрут",
                   "type": "map", "version": "1.4.0",
                   "depends": ["sound-pack"]}, f, ensure_ascii=False)

    # Пакет-архив (дополнение)
    zsrc = os.path.join(src, "sound_pack.zip")
    with zipfile.ZipFile(zsrc, "w") as zf:
        zf.writestr("mddl.json", json.dumps({
            "id": "sound-pack", "name": "Звуки",
            "type": "addon", "version": "3.0.0"}))
        zf.writestr("GLOBAL/SOUNDS/pack.txt", "sound-data")

    repo = os.path.join(tmp6, "repo")
    entries = build_repo(src, repo, verbose=False)
    check("make_repo: 2 пакета", len(entries) == 2, str(len(entries)))

    m = load_manifest(RepoClient([repo]))
    check("make_repo: манифест читается", len(m.packages) == 2)
    check("make_repo: версии из mddl.json",
          m.get("cool-route").version == "1.4.0"
          and m.get("sound-pack").version == "3.0.0")
    check("make_repo: sha256 сходится",
          all(p.sha256 for p in m.packages))

    # Полный реальный цикл: зеркало -> скачать -> проверить -> установить
    g2 = os.path.join(tmp6, "game2")
    os.makedirs(g2)
    inst2 = Installer(g2)
    dl = RepoClient([repo])
    pkgs, _, _ = resolve(m, ["cool-route"], auto_addons=True)
    ids = [p.id for p in pkgs]
    check("make_repo: depends тянет звуки", "sound-pack" in ids, str(ids))
    for p in pkgs:
        dest = inst2.cache_path(p)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        dl.download(p.file, dest, sha256=p.sha256)
        inst2.install_package(p, dest)
    check("реальный цикл: файлы на месте",
          os.path.isfile(os.path.join(g2, "ROUTES", "CoolRoute",
                                       "routes.txt"))
          and os.path.isfile(os.path.join(g2, "GLOBAL", "SOUNDS",
                                          "pack.txt")))
    check("реальный цикл: реестр", len(inst2.installed()) == 2)
    # mddl.json из пакета не должен попасть в игру
    check("реальный цикл: mddl.json не установлен",
          not os.path.isfile(os.path.join(g2, "mddl.json")))

# 11. Демо отключено по умолчанию (в продукте только реальный контент)
with tempfile.TemporaryDirectory() as tmp7:
    cfg = Config(os.path.join(tmp7, "config.json"))
    check("демо выключено по умолчанию", cfg.get("use_demo_repo") is False)

# 12. Скачивание по прямой ссылке (fetch_url_to) — локальный HTTP-сервер
import functools  # noqa: E402
import http.server  # noqa: E402
import threading  # noqa: E402

from core.net import Cancelled, fetch_url_to  # noqa: E402

with tempfile.TemporaryDirectory() as tmp9:
    payload = b"PK\x03\x04-real-url-bytes-" + os.urandom(64 * 1024)
    with open(os.path.join(tmp9, "archive.zip"), "wb") as f:
        f.write(payload)

    class _Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D102
            pass

    handler = functools.partial(_Quiet, directory=tmp9)
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        dest = os.path.join(tmp9, "out", "got.zip")
        seen = []
        got_path, nbytes = fetch_url_to(
            f"http://127.0.0.1:{port}/archive.zip", dest,
            progress=lambda d, t: seen.append((d, t)))
        check("url: файл скачан", os.path.isfile(dest) and nbytes == len(payload))
        with open(dest, "rb") as f:
            check("url: содержимое совпало", f.read() == payload)
        check("url: прогресс вызван", bool(seen) and seen[-1][0] == len(payload),
              str(seen[-1:]))

        try:
            fetch_url_to(f"http://127.0.0.1:{port}/missing.zip",
                         os.path.join(tmp9, "nope.zip"))
            check("url: 404 -> ошибка", False)
        except Exception:
            check("url: 404 -> ошибка", True)
        check("url: не оставил хвостов",
              not os.path.isfile(os.path.join(tmp9, "nope.zip"))
              and not os.path.isfile(os.path.join(tmp9, "nope.zip.part")))

        try:
            fetch_url_to(f"http://127.0.0.1:{port}/archive.zip",
                         os.path.join(tmp9, "cancel.zip"),
                         cancel=lambda: True)
            check("url: отмена -> Cancelled", False)
        except Cancelled:
            check("url: отмена -> Cancelled", True)
        check("url: отмена убрала .part",
              not os.path.isfile(os.path.join(tmp9, "cancel.zip.part")))
    finally:
        httpd.shutdown()
        httpd.server_close()

print()
if fails:
    print(f"FAILED: {len(fails)} -> {fails}")
    sys.exit(1)
print("ALL TESTS PASSED")
