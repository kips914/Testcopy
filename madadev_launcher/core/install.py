# -*- coding: utf-8 -*-
"""Установка пакетов в папку игры и реестр установленного.

Пакет — ZIP-архив с файлами, относительно папки игры
(``ROUTES/...``, ``TRAINS/...``, ``GLOBAL/...``).
Реестр хранится в ``<папка игры>/.mddl/installed.json``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone

from .manifest import KNOWN_TYPES
from .net import sha256_file


def fmt_size(num: int) -> str:
    """Человекочитаемый размер файла."""
    try:
        num = int(num or 0)
    except (TypeError, ValueError):
        return "?"
    step = 1024.0
    value = float(num)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < step or unit == "ТБ":
            if unit == "Б":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= step
    return f"{num} Б"


def parse_version(version: str) -> tuple:
    """Сравнимая кортеж-версия: '1.2.10' -> (1, 2, 10)."""
    return tuple(int(x) for x in re.findall(r"\d+", str(version or "")))


def version_cmp(a: str, b: str) -> int:
    va, vb = parse_version(a), parse_version(b)
    # Добиваем нулями, чтобы (1,2) == (1,2,0)
    length = max(len(va), len(vb))
    va = va + (0,) * (length - len(va))
    vb = vb + (0,) * (length - len(vb))
    return (va > vb) - (va < vb)


# ---------------------------------------------------------------------------
# Реальная установка из локальных источников (архивы, папки)
# ---------------------------------------------------------------------------

def sanitize_package_id(raw) -> str:
    """Чистый id пакета: a-z, 0-9, точка, дефис, подчёркивание."""
    raw = str(raw or "").strip().lower()
    raw = re.sub(r"[^a-z0-9._-]+", "-", raw)
    return raw.strip("-._") or "package"


def read_package_meta(source) -> dict:
    """Прочитать ``mddl.json`` из архива или папки. Пустой dict, если нет."""
    try:
        if os.path.isfile(source) and zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as zf:
                if "mddl.json" in zf.namelist():
                    data = json.loads(zf.read("mddl.json").decode("utf-8-sig"))
                    return data if isinstance(data, dict) else {}
        elif os.path.isdir(source):
            path = os.path.join(source, "mddl.json")
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — битый meta не должен ронять установку
        return {}
    return {}


def guess_package_type(rel_paths) -> str:
    """Определить тип пакета по структуре файлов."""
    lower = [str(p).replace("\\", "/").lower() for p in rel_paths]
    if any(p.startswith("routes/") and "/activities/" in p for p in lower):
        return "scenario"
    if any(p.startswith("routes/") for p in lower):
        return "map"
    if any(p.startswith("trains/") for p in lower):
        return "mod"
    return "addon"


def looks_like_game_tree(names) -> bool:
    """Есть ли среди верхнеуровневых записей игровые каталоги.

    MaDaDev RTS — это RTrainSim (наследник MSTS): корень игры содержит
    ``ROUTES``, ``TRAINS``, ``GLOBAL``, ``SOUND``, ``GUI``; у openRTS
    добавляются ``PACKS`` и ``MODS_OPENRTS``. ``SOUNDS`` — вариант
    написания из старых сборок.
    """
    tops = {str(n).replace("\\", "/").split("/")[0].lower()
            for n in names if str(n).strip()}
    return bool(tops & {"routes", "trains", "global",
                        "sound", "sounds", "gui", "packs"})


class Installer:
    """Ставит/удаляет пакеты в папку игры и помнит, что установлено."""

    def __init__(self, game_dir: str):
        self.game_dir = os.path.abspath(game_dir) if game_dir else ""
        self.state_dir = os.path.join(self.game_dir, ".mddl")
        self.state_path = os.path.join(self.state_dir, "installed.json")
        self.cache_dir = os.path.join(self.state_dir, "cache")

    # ------------------------------------------------------------------ #
    @property
    def ready(self) -> bool:
        return bool(self.game_dir) and os.path.isdir(self.game_dir)

    def _load_state(self) -> dict:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("packages"), dict):
                return data
        except (FileNotFoundError, ValueError, OSError):
            pass
        return {"packages": {}}

    def _save_state(self, state: dict) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)

    def installed(self) -> dict:
        """id -> запись о пакете (version, name, type, files…)."""
        if not self.game_dir:
            return {}
        return dict(self._load_state()["packages"])

    def entry(self, pkg_id: str):
        return self.installed().get(pkg_id)

    def cache_path(self, pkg) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", pkg.id)
        ver = re.sub(r"[^A-Za-z0-9._-]+", "_", pkg.version)
        return os.path.join(self.cache_dir, f"{safe}-{ver}.zip")

    def is_cached(self, pkg) -> bool:
        path = self.cache_path(pkg)
        if not os.path.isfile(path):
            return False
        if pkg.size and os.path.getsize(path) != pkg.size:
            return False
        if pkg.sha256:
            try:
                return sha256_file(path).lower() == pkg.sha256.lower()
            except OSError:
                return False
        return True

    # ------------------------------------------------------------------ #
    def status(self, pkg) -> str:
        """'installed' | 'update' | 'missing'."""
        entry = self.entry(pkg.id)
        if not entry:
            return "missing"
        # Доступно обновление, только если в репозитории версия новее установленной.
        if version_cmp(str(entry.get("version", "")), pkg.version) < 0:
            return "update"
        return "installed"

    def status_label(self, pkg) -> str:
        if not self.ready:
            return "—"
        st = self.status(pkg)
        if st == "installed":
            return "Установлено"
        if st == "update":
            return "Есть обновление"
        return "—"

    # ------------------------------------------------------------------ #
    @staticmethod
    def _safe_names(zf: zipfile.ZipFile) -> list:
        names = []
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            if not name or name.startswith("/") or ".." in name.split("/"):
                raise RuntimeError(f"небезопасный путь в архиве: {info.filename}")
            if len(name) > 1 and name[1] == ":":
                raise RuntimeError(f"абсолютный путь в архиве: {info.filename}")
            names.append(info)
        return names

    def install_package(self, pkg, zip_path: str, progress=None) -> int:
        """Распаковать пакет в папку игры. Возвращает число файлов.

        Старая версия пакета (если есть) перед этим удаляется.
        """
        if not self.ready:
            raise RuntimeError("не выбрана папка с игрой")
        state = self._load_state()
        entry = state["packages"].get(pkg.id)

        # Обновление: сначала убираем файлы прошлой версии.
        if entry and str(entry.get("version", "")) != pkg.version:
            self._remove_files(entry.get("files") or [])

        os.makedirs(self.game_dir, exist_ok=True)
        if entry and str(entry.get("version", "")) == pkg.version:
            installed_files = list(entry.get("files") or [])
        else:
            installed_files = []
        new_files = []

        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = [i for i in self._safe_names(zf)
                     if i.filename.replace("\\", "/").lower() != "mddl.json"]
            total = len(infos) or 1
            for idx, info in enumerate(infos, 1):
                target = os.path.join(self.game_dir, *info.filename.replace("\\", "/").split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                rel = info.filename.replace("\\", "/")
                if rel not in installed_files:
                    new_files.append(rel)
                if progress is not None:
                    progress(idx, total)

        all_files = installed_files + new_files
        state["packages"][pkg.id] = {
            "id": pkg.id,
            "name": pkg.name,
            "type": pkg.type,
            "version": pkg.version,
            "files": all_files,
            "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._save_state(state)
        return len(new_files)

    def _remove_files(self, files) -> None:
        base = os.path.abspath(self.game_dir)
        dirs = set()
        for rel in files:
            rel = str(rel).replace("\\", "/")
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            path = os.path.abspath(os.path.join(base, *rel.split("/")))
            try:
                if os.path.commonpath([base, path]) != base:
                    continue
            except ValueError:
                # Разные диски на Windows — не наш файл.
                continue
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    dirs.add(os.path.dirname(path))
            except OSError:
                pass
        # Подчищаем пустые каталоги (снизу вверх), но не сами игровые папки.
        keep = {base, os.path.join(base, ".mddl")}
        for d in sorted(dirs, key=lambda p: p.count(os.sep), reverse=True):
            cur = d
            while cur.startswith(base) and cur not in keep:
                try:
                    if os.path.isdir(cur) and not os.listdir(cur):
                        os.rmdir(cur)
                        cur = os.path.dirname(cur)
                    else:
                        break
                except OSError:
                    break

    def uninstall(self, pkg_id: str) -> bool:
        """Удалить пакет и его файлы. True, если что-то было удалено."""
        state = self._load_state()
        entry = state["packages"].pop(pkg_id, None)
        if entry is None:
            return False
        self._remove_files(entry.get("files") or [])
        self._save_state(state)
        return True

    # ------------------------------------------------------------------ #
    # Реальная установка из .zip / папки (без репозитория)
    # ------------------------------------------------------------------ #
    def install_local(self, source, meta=None, progress=None) -> dict:
        """Установить реальный пакет из архива или папки в папку игры.

        * ``source`` — путь к ``.zip`` либо к папке с игровой структурой
          (``ROUTES/…``, ``TRAINS/…``, ``GLOBAL/…``);
        * ``meta`` — метаданные (обычно из ``mddl.json``): ``id``, ``name``,
          ``type``, ``version``, ``description``, ``depends``, ``addons``.
          Без них id/имя берутся из имени файла, тип определяется по
          структуре файлов;
        * файл ``mddl.json`` — метаданные, в игру не распаковывается.

        Возвращает запись реестра установленного.
        """
        if not self.ready:
            raise RuntimeError("не выбрана папка с игрой")
        source = os.path.abspath(source)
        meta = dict(meta or {})
        is_zip = os.path.isfile(source) and zipfile.is_zipfile(source)
        if not is_zip and not os.path.isdir(source):
            raise RuntimeError(f"это не архив .zip и не папка: {source}")

        # 1. Собрать список файлов (защита путей + определение типа).
        if is_zip:
            with zipfile.ZipFile(source) as zf:
                infos = self._safe_names(zf)
                rels = [i.filename.replace("\\", "/") for i in infos]
        else:
            infos = None
            rels = []
            for root, dirs, files in os.walk(source):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, source).replace("\\", "/")
                    if rel.startswith("/") or ".." in rel.split("/"):
                        raise RuntimeError(f"небезопасный путь в папке: {rel}")
                    rels.append(rel)
        install_rels = [r for r in rels if r.lower() != "mddl.json"]
        if not install_rels:
            raise RuntimeError("нет файлов игры для установки "
                              "(нужны ROUTES/…, TRAINS/…, GLOBAL/…)")

        # 2. Метаданные пакета.
        base_name = os.path.splitext(os.path.basename(source.rstrip("/\\")))[0]
        pkg_id = sanitize_package_id(meta.get("id") or base_name)
        name = str(meta.get("name") or base_name or pkg_id)
        ptype = str(meta.get("type") or "").strip().lower()
        if ptype not in KNOWN_TYPES:
            ptype = guess_package_type(install_rels)
        version = str(meta.get("version") or "1.0.0")
        depends = ([str(d) for d in meta["depends"]]
                   if isinstance(meta.get("depends"), list) else [])
        addons = ([str(a) for a in meta["addons"]]
                  if isinstance(meta.get("addons"), list) else [])
        description = str(meta.get("description") or "")

        # 3. Убрать предыдущую версию этого пакета (если была).
        state = self._load_state()
        old = state["packages"].get(pkg_id)
        if old:
            self._remove_files(old.get("files") or [])

        # 4. Распаковать в папку игры.
        collected = []
        total = len(install_rels)
        if is_zip:
            with zipfile.ZipFile(source) as zf:
                safe = [i for i in self._safe_names(zf)
                        if i.filename.replace("\\", "/").lower() != "mddl.json"]
                for idx, info in enumerate(safe, 1):
                    rel = info.filename.replace("\\", "/")
                    target = os.path.join(self.game_dir, *rel.split("/"))
                    os.makedirs(os.path.dirname(target) or self.game_dir,
                                exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
                    collected.append(rel)
                    if progress is not None:
                        progress(idx, total)
        else:
            for idx, rel in enumerate(install_rels, 1):
                src_path = os.path.join(source, *rel.split("/"))
                target = os.path.join(self.game_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(target) or self.game_dir,
                            exist_ok=True)
                shutil.copyfile(src_path, target)
                collected.append(rel)
                if progress is not None:
                    progress(idx, total)

        entry = {
            "id": pkg_id,
            "name": name,
            "type": ptype,
            "version": version,
            "description": description,
            "depends": depends,
            "addons": addons,
            "files": collected,
            "source": "archive" if is_zip else "folder",
            "installed_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
        }
        state["packages"][pkg_id] = entry
        self._save_state(state)
        return entry

    def clear_cache(self) -> int:
        """Удалить скачанные архивы. Возвращает освобождённых байтов."""
        freed = 0
        if not os.path.isdir(self.cache_dir):
            return 0
        for name in os.listdir(self.cache_dir):
            path = os.path.join(self.cache_dir, name)
            try:
                if os.path.isfile(path):
                    freed += os.path.getsize(path)
                    os.remove(path)
            except OSError:
                pass
        return freed
