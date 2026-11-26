# -*- coding: utf-8 -*-
"""Манифест репозитория и разрешение зависимостей.

Манифест — обычный JSON-файл `manifest.json` в корне зеркала.
Каждый пакет может тянуть за собой зависимости (`depends`) и
дополнения (`addons`) — лаунчер подтягивает их автоматически.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field

KNOWN_TYPES = ("map", "scenario", "mod", "addon", "base", "bundle")

TYPE_LABELS = {
    "map": "Карта",
    "scenario": "Сценарий",
    "mod": "Мод",
    "addon": "Дополнение",
    "base": "База",
    "bundle": "Набор",
}


class ManifestError(Exception):
    """Ошибка загрузки или разбора манифеста."""


@dataclass
class Package:
    """Один пакет из каталога (карта, сценарий, мод, дополнение…)."""

    id: str
    name: str
    type: str = "mod"
    version: str = "1.0.0"
    file: str = ""
    size: int = 0
    sha256: str = ""
    description: str = ""
    depends: list = field(default_factory=list)
    addons: list = field(default_factory=list)

    @property
    def type_label(self) -> str:
        return TYPE_LABELS.get(self.type, self.type)

    @classmethod
    def from_dict(cls, data: dict) -> "Package | None":
        if not isinstance(data, dict):
            return None
        pid = str(data.get("id") or "").strip()
        if not pid:
            return None
        pkg_type = str(data.get("type") or "mod").lower().strip()
        if pkg_type not in KNOWN_TYPES:
            pkg_type = "mod"

        def str_list(key: str) -> list:
            value = data.get(key) or []
            if not isinstance(value, list):
                return []
            return [str(v).strip() for v in value if str(v).strip()]

        try:
            size = int(data.get("size") or 0)
        except (TypeError, ValueError):
            size = 0

        return cls(
            id=pid,
            name=str(data.get("name") or pid),
            type=pkg_type,
            version=str(data.get("version") or "1.0.0"),
            file=str(data.get("file") or ""),
            size=max(0, size),
            sha256=str(data.get("sha256") or ""),
            description=str(data.get("description") or ""),
            depends=str_list("depends"),
            addons=str_list("addons"),
        )


@dataclass
class Manifest:
    """Содержимое manifest.json."""

    name: str = "Репозиторий"
    schema: int = 1
    packages: list = field(default_factory=list)
    _by_id: dict = None  # type: ignore[assignment]

    @classmethod
    def from_dict(cls, data: dict) -> "Manifest":
        if not isinstance(data, dict):
            raise ManifestError("манифест должен быть JSON-объектом")
        raw_packages = data.get("packages")
        if not isinstance(raw_packages, list):
            raise ManifestError("в манифесте нет списка «packages»")
        packages = []
        for item in raw_packages:
            pkg = Package.from_dict(item)
            if pkg is not None and pkg.file:
                packages.append(pkg)
        if not packages:
            raise ManifestError("в манифесте нет пакетов")
        try:
            schema = int(data.get("schema") or 1)
        except (TypeError, ValueError):
            schema = 1
        return cls(
            name=str(data.get("name") or "Репозиторий"),
            schema=schema,
            packages=packages,
        )

    def by_id(self) -> dict:
        """Словарь id -> Package (лениво, с кешем)."""
        if self._by_id is None:
            self._by_id = {p.id: p for p in self.packages}
        return self._by_id

    def get(self, pid: str):
        return self.by_id().get(pid)


def load_manifest(client) -> Manifest:
    """Скачать и разобрать manifest.json через RepoClient."""
    raw = client.fetch("manifest.json")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ManifestError(f"manifest.json не читается: {exc}") from exc
    return Manifest.from_dict(data)


def resolve(
    manifest: Manifest,
    requested_ids,
    auto_addons: bool = True,
):
    """Разрешить набор запрошенных пакетов.

    Возвращает ``(packages, pulled_ids, missing_ids)``:
    * ``packages`` — пакеты в порядке установки (зависимости раньше);
    * ``pulled_ids`` — пакеты, подтянутые автоматически
      (зависимости и дополнения), т.е. «все дополнения»;
    * ``missing_ids`` — id, которых нет в каталоге.
    """
    by_id = manifest.by_id()
    requested = [str(i) for i in requested_ids]
    known_requested = [i for i in requested if i in by_id]
    missing = [i for i in requested if i not in by_id]

    # 1. Замыкание: зависимости + (опционально) дополнения, рекурсивно.
    discovery: list = []
    seen: set = set()
    queue: deque = deque(known_requested)
    while queue:
        pid = queue.popleft()
        if pid in seen:
            continue
        pkg = by_id.get(pid)
        if pkg is None:
            if pid not in missing:
                missing.append(pid)
            continue
        seen.add(pid)
        discovery.append(pid)
        for dep in pkg.depends:
            queue.append(dep)
        if auto_addons:
            for addon in pkg.addons:
                queue.append(addon)

    if not discovery:
        return [], [], missing

    # 2. Топологическая сортировка по ``depends`` (зависимости раньше).
    indeg = {pid: 0 for pid in seen}
    edges = {pid: [] for pid in seen}
    for pid in seen:
        for dep in by_id[pid].depends:
            if dep in seen:
                indeg[pid] += 1
                edges[dep].append(pid)

    ready = deque(pid for pid in discovery if indeg[pid] == 0)
    order: list = []
    while ready:
        pid = ready.popleft()
        order.append(pid)
        for nxt in edges[pid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)

    # 3. Если в зависимостях цикл — не зацикливаемся, берём порядок обнаружения.
    if len(order) < len(seen):
        for pid in discovery:
            if pid not in order:
                order.append(pid)

    requested_set = set(known_requested)
    pulled = [pid for pid in order if pid not in requested_set]
    return [by_id[pid] for pid in order], pulled, missing
