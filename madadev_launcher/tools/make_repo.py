#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Собрать НАСТОЯЩИЙ репозиторий лаунчера из папки с реальными модами и картами.

Источник (``src``):
  * каждая подпапка — пакет: внутри игровая структура (``ROUTES/…``,
    ``TRAINS/…``, ``GLOBAL/…``) и необязательный ``mddl.json``
    с метаданными (id, name, type, version, depends, addons);
  * каждый ``*.zip`` — готовый пакет (метаданные читаются из ``mddl.json``
    внутри архива).

Выход (``dst``): ``manifest.json`` + ``packages/<id>-<version>.zip`` —
полноценное зеркало для лаунчера. Клади его на любой HTTP-сервер или в
общую папку и добавляй в Настройки → Зеркала.

Запуск::

    python tools/make_repo.py D:\\my_mods D:\\rts_repo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.install import (  # noqa: E402
    guess_package_type,
    read_package_meta,
    sanitize_package_id,
)
from core.manifest import KNOWN_TYPES, TYPE_LABELS  # noqa: E402


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(256 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip_folder(folder: str, dest_zip: str) -> list:
    """Упаковать папку пакета в zip. Возвращает список относительных путей."""
    rels = []
    os.makedirs(os.path.dirname(dest_zip), exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for fn in sorted(files):
                if fn.startswith("."):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, folder).replace("\\", "/")
                if rel.startswith("/") or ".." in rel.split("/"):
                    continue
                zf.write(full, rel)
                rels.append(rel)
    return rels


def _make_entry(pkg_id: str, meta: dict, rels: list, file_rel: str,
                size: int, sha: str) -> dict:
    ptype = str(meta.get("type") or "").strip().lower()
    if ptype not in KNOWN_TYPES:
        ptype = guess_package_type(rels)

    def str_list(key: str) -> list:
        value = meta.get(key)
        if isinstance(value, list):
            return [str(v) for v in value]
        return []

    return {
        "id": pkg_id,
        "name": str(meta.get("name") or pkg_id),
        "type": ptype,
        "version": str(meta.get("version") or "1.0.0"),
        "description": str(meta.get("description") or ""),
        "depends": str_list("depends"),
        "addons": str_list("addons"),
        "file": file_rel,
        "size": size,
        "sha256": sha,
    }


def _unique_id(base: str, used: set) -> str:
    pkg_id = base
    n = 2
    while pkg_id in used:
        pkg_id = f"{base}-{n}"
        n += 1
    used.add(pkg_id)
    return pkg_id


def build_repo(src: str, dst: str, verbose: bool = True) -> list:
    """Собрать репозиторий из ``src`` в ``dst``. Возвращает записи манифеста."""
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    if not os.path.isdir(src):
        raise SystemExit(f"папка-источник не найдена: {src}")
    if os.path.abspath(src) == os.path.abspath(dst):
        raise SystemExit("папка источника и репозитория должны различаться")

    packages_dir = os.path.join(dst, "packages")
    os.makedirs(packages_dir, exist_ok=True)
    entries: list = []
    used_ids: set = set()

    # 1. Папки-пакеты
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if name.startswith(".") or not os.path.isdir(path):
            continue
        meta = read_package_meta(path)
        pkg_id = _unique_id(sanitize_package_id(meta.get("id") or name),
                            used_ids)
        version = str(meta.get("version") or "1.0.0")
        file_rel = f"packages/{pkg_id}-{version}.zip"
        dest_zip = os.path.join(dst, *file_rel.split("/"))
        rels = _zip_folder(path, dest_zip)
        if not rels:
            try:
                os.remove(dest_zip)
            except OSError:
                pass
            if verbose:
                print(f"  пропуск пустой папки: {name}")
            continue
        entry = _make_entry(pkg_id, meta, rels, file_rel,
                            os.path.getsize(dest_zip),
                            _sha256_file(dest_zip))
        entries.append(entry)
        if verbose:
            print(f"  + {entry['name']} ({TYPE_LABELS.get(entry['type'], entry['type'])}, "
                  f"{entry['version']}) — {len(rels)} файлов")

    # 2. Готовые архивы
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if name.startswith(".") or not name.lower().endswith(".zip"):
            continue
        if not os.path.isfile(path) or not zipfile.is_zipfile(path):
            if verbose:
                print(f"  пропуск (не zip): {name}")
            continue
        meta = read_package_meta(path)
        stem = os.path.splitext(name)[0]
        pkg_id = _unique_id(sanitize_package_id(meta.get("id") or stem),
                            used_ids)
        version = str(meta.get("version") or "1.0.0")
        file_rel = f"packages/{pkg_id}-{version}.zip"
        dest_zip = os.path.join(dst, *file_rel.split("/"))
        shutil.copyfile(path, dest_zip)
        with zipfile.ZipFile(path) as zf:
            rels = [i.filename.replace("\\", "/") for i in zf.infolist()
                    if not i.is_dir()]
        entry = _make_entry(pkg_id, meta, rels, file_rel,
                            os.path.getsize(dest_zip),
                            _sha256_file(dest_zip))
        entries.append(entry)
        if verbose:
            print(f"  + {entry['name']} ({TYPE_LABELS.get(entry['type'], entry['type'])}, "
                  f"{entry['version']}) — {len(rels)} файлов")

    if not entries:
        raise SystemExit(f"в {src} не найдено ни одного пакета "
                         "(подпапки с файлами игры или .zip)")

    manifest = {
        "schema": 1,
        "name": f"Репозиторий {os.path.basename(dst)}",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "packages": entries,
    }
    manifest_path = os.path.join(dst, "manifest.json")
    tmp = manifest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, manifest_path)

    if verbose:
        counts = Counter(e["type"] for e in entries)
        summary = ", ".join(f"{TYPE_LABELS.get(t, t)}: {n}"
                            for t, n in sorted(counts.items()))
        print(f"\nГотово: {len(entries)} пакетов -> {manifest_path}")
        print(f"  {summary}")
        print("  Добавь эту папку (или её URL) как зеркало в настройках "
              "лаунчера.")
    return entries


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Собрать репозиторий лаунчера из папки с модами/картами")
    parser.add_argument("src", help="папка с пакетами (подпапки или .zip)")
    parser.add_argument("dst", help="куда собрать репозиторий")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="без печати списка")
    args = parser.parse_args(argv)
    build_repo(args.src, args.dst, verbose=not args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
