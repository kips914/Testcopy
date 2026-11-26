# -*- coding: utf-8 -*-
"""Клиент репозитория: зеркала (HTTP/HTTPS или локальная папка),
резумируемое скачивание с проверкой SHA-256 и прогрессом."""

from __future__ import annotations

import hashlib
import os
import time
import urllib.parse
import urllib.request


class RepoError(Exception):
    """Ошибка обращения к зеркалу репозитория."""


class Cancelled(Exception):
    """Пользователь отменил операцию."""


CHUNK = 256 * 1024
USER_AGENT = "MaDaDev-Launcher/1.0"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class RepoClient:
    """Доступ к файлам репозитория через список зеркал.

    Зеркало — либо URL (``https://host/path``), либо локальная папка
    (или ``file:///...``), в которой лежит ``manifest.json``.
    Активное зеркало пробуется первым, при сбое — остальные.
    """

    def __init__(self, mirrors, timeout: int = 30):
        self.mirrors = [str(m).strip() for m in (mirrors or []) if str(m).strip()]
        self.timeout = max(5, int(timeout or 30))
        self.active = 0

    # ------------------------------------------------------------------ #
    def set_active(self, index: int) -> None:
        if self.mirrors:
            self.active = int(index) % len(self.mirrors)

    @property
    def active_mirror(self):
        if not self.mirrors:
            return None
        return self.mirrors[self.active % len(self.mirrors)]

    @staticmethod
    def _is_local(base: str) -> bool:
        return base.startswith("file://") or "://" not in base

    @staticmethod
    def _local_path(base: str) -> str:
        if base.startswith("file://"):
            parsed = urllib.parse.urlparse(base)
            path = urllib.parse.unquote(parsed.path)
            # file:///C:/dir -> /C:/dir -> C:/dir (Windows)
            if len(path) > 2 and path[0] == "/" and path[2] == ":":
                path = path[1:]
            return path
        return base

    def _full(self, base: str, rel: str) -> str:
        rel = str(rel).replace("\\", "/").lstrip("/")
        if self._is_local(base):
            return os.path.join(self._local_path(base), *rel.split("/"))
        return base.rstrip("/") + "/" + rel

    def _order(self) -> list:
        if not self.mirrors:
            return []
        n = len(self.mirrors)
        first = self.active % n
        return [self.mirrors[first]] + [self.mirrors[i] for i in range(n) if i != first]

    # ------------------------------------------------------------------ #
    def fetch(self, rel: str, max_tries: int = 2) -> bytes:
        """Прочитать небольшой файл (например, manifest.json)."""
        if not self.mirrors:
            raise RepoError("нет зеркал репозитория — добавь их в настройках")
        last_err = None
        for base in self._order():
            for _ in range(max_tries):
                try:
                    if self._is_local(base):
                        with open(self._full(base, rel), "rb") as f:
                            return f.read()
                    req = urllib.request.Request(
                        self._full(base, rel),
                        headers={"User-Agent": USER_AGENT},
                    )
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        return resp.read()
                except Exception as exc:  # noqa: BLE001 — пробуем следующее зеркало
                    last_err = exc
                    time.sleep(0.3)
        raise RepoError(f"не удалось получить {rel}: {last_err}")

    # ------------------------------------------------------------------ #
    def _open_source(self, base: str, rel: str, offset: int):
        """Открыть файл-источник с учётом смещения (резум). Возвращает (fp, total)."""
        if self._is_local(base):
            path = self._full(base, rel)
            fp = open(path, "rb")
            total = os.path.getsize(path)
            if offset:
                if offset >= total:
                    fp.close()
                    raise RepoError("файл изменился на зеркале")
                fp.seek(offset)
            return fp, total
        headers = {"User-Agent": USER_AGENT}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        req = urllib.request.Request(self._full(base, rel), headers=headers)
        resp = urllib.request.urlopen(req, timeout=self.timeout)
        total_hdr = resp.headers.get("Content-Length")
        try:
            total_hdr = int(total_hdr) if total_hdr is not None else None
        except ValueError:
            total_hdr = None
        if offset and resp.status == 206 and total_hdr is not None:
            total = offset + total_hdr
        elif total_hdr is not None:
            total = total_hdr
        else:
            total = None
        return resp, total

    def _download_from(
        self,
        base: str,
        rel: str,
        part_path: str,
        progress,
        cancel,
    ) -> None:
        offset = os.path.getsize(part_path) if os.path.exists(part_path) else 0
        source, total = self._open_source(base, rel, offset)
        mode = "ab" if offset else "wb"
        done = offset
        try:
            with open(part_path, mode) as out:
                while True:
                    if cancel is not None and cancel():
                        raise Cancelled()
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total if total else done)
        finally:
            try:
                source.close()
            except Exception:
                pass
        if total is not None and done < total:
            raise RepoError("загрузка оборвалась (неполный файл)")

    def download(
        self,
        rel: str,
        dest: str,
        sha256: str = "",
        progress=None,
        cancel=None,
        max_tries: int = 2,
    ) -> str:
        """Скачать файл в ``dest`` (через ``.part``), проверить SHA-256.

        ``progress(done, total)`` вызывается по ходу загрузки.
        ``cancel()`` — колбэк, возвращающий True, если нужно прерваться.
        """
        if not self.mirrors:
            raise RepoError("нет зеркал репозитория — добавь их в настройках")
        dest = os.path.abspath(dest)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        part = dest + ".part"
        last_err = None
        for base in self._order():
            for _ in range(max_tries):
                if cancel is not None and cancel():
                    raise Cancelled()
                try:
                    self._download_from(base, rel, part, progress, cancel)
                    if sha256:
                        actual = sha256_file(part)
                        if actual.lower() != str(sha256).lower():
                            # Файл битый — начинаем заново с этого зеркала.
                            if os.path.exists(part):
                                os.remove(part)
                            last_err = RepoError(
                                f"контрольная сумма не совпала ({rel})"
                            )
                            continue
                    os.replace(part, dest)
                    return dest
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    time.sleep(0.3)
        raise RepoError(f"не удалось скачать {rel}: {last_err}")
