#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MaDaDev RTS — лаунчер.

Скачивает карты, сценарии и моды из репозитория-зеркала, автоматически
подтягивает все дополнения и зависимости, ставит их в папку игры и
запускает симулятор.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from datetime import datetime

# Запуск из исходников: рядом должна лежать пакет core/ (в exe он вшит).
if not getattr(sys, "frozen", False):
    _SRC_DIR = os.path.dirname(os.path.abspath(__file__))
    if _SRC_DIR not in sys.path:
        sys.path.insert(0, _SRC_DIR)

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError:  # pragma: no cover
    print(
        "Не найден tkinter. Установи обычный установщик Python "
        "(python.org) с галочкой tcl/tk и запусти ещё раз."
    )
    sys.exit(1)

from core import paths as app_paths
from core.config import Config
from core.demo import ensure_demo_repo
from core.install import (Installer, fmt_size, looks_like_game_tree,
                          read_package_meta)
from core.manifest import TYPE_LABELS, Manifest, load_manifest, resolve
from core.net import Cancelled, RepoClient

APP_TITLE = "MaDaDev RTS — Лаунчер"
APP_VERSION = "1.0.0"
# Папка exe (в собранном виде) или папка исходников — сюда пишутся
# config.json, demo_repo/ и launcher_error.log.
BASE_DIR = app_paths.app_dir()
# Ресурсы: вшитые в exe (sys._MEIPASS) либо папка исходников.
RESOURCE_DIR = app_paths.resource_dir()

# Палитра
BG = "#12141a"
PANEL = "#1a1d26"
PANEL2 = "#242836"
TEXT = "#e8eaf0"
MUTED = "#8b93a7"
ACCENT = "#3d8bfd"
OK = "#3ddc84"
WARN = "#ffb454"
ERR = "#ff6b6b"

TYPE_FILTERS = [
    ("all", "Все типы"),
    ("map", "Карты"),
    ("scenario", "Сценарии"),
    ("mod", "Моды"),
    ("addon", "Дополнения"),
    ("base", "База"),
    ("bundle", "Наборы"),
]

GAME_EXE_PREFERRED = [
    "rts.exe",
    "msts.exe",
    "train.exe",
    "rtstrainsim.exe",
    "rtrainsim.exe",
    "realtrainsim.exe",
]
EXE_EXCLUDE = ("unins", "setup", "install", "uninstall", "mddl", "crash", "update")


class LauncherApp:
    def __init__(self, root: "tk.Tk"):
        self.root = root
        self.q: "queue.Queue" = queue.Queue()
        self.job_cancel = threading.Event()
        self.job_running = False
        self.manifest: Manifest | None = None

        self.cfg = Config(os.path.join(BASE_DIR, "config.json"))
        self.installer = Installer(self.cfg.get("game_dir") or "")

        root.title(f"{APP_TITLE}  ·  v{APP_VERSION}")
        root.geometry(self.cfg.get("window_geometry") or "1080x680")
        root.minsize(940, 580)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._apply_window_icon(root)

        self._build_style()
        self._build_ui()

        self.rebuild_client()
        self.refresh_catalog()
        self._refresh_installed()
        self.root.after(80, self._poll)

    # ------------------------------------------------------------------ #
    # Стили
    # ------------------------------------------------------------------ #
    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=PANEL, foreground=TEXT, fieldbackground=PANEL,
                        bordercolor=PANEL2, lightcolor=PANEL, darkcolor=PANEL)
        style.configure("TFrame", background=PANEL)
        style.configure("Bg.TFrame", background=BG)
        style.configure("TLabel", background=PANEL, foreground=TEXT)
        style.configure("Bg.TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT,
                        font=("Segoe UI", 16, "bold"))
        style.configure("TButton", background=PANEL2, foreground=TEXT,
                        padding=(12, 6), focuscolor=PANEL2)
        style.map("TButton",
                  background=[("active", "#2d3346"), ("pressed", "#343b52")],
                  foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        padding=(14, 7))
        style.map("Accent.TButton",
                  background=[("active", "#5a9dff"), ("pressed", "#2f7ae0")],
                  foreground=[("disabled", "#9fb6d8")])
        style.configure("Danger.TButton", background="#5a2530", foreground="#ffb3ba",
                        padding=(12, 6))
        style.map("Danger.TButton", background=[("active", "#74303d")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL2, foreground=TEXT,
                        padding=(14, 7))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])
        style.configure("Treeview", background=PANEL, foreground=TEXT,
                        fieldbackground=PANEL, rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background=PANEL2, foreground=TEXT,
                        padding=(6, 6), font=("Segoe UI", 10, "bold"))
        style.map("Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])
        style.configure("Horizontal.TProgressbar", background=ACCENT,
                        troughcolor=PANEL2, bordercolor=PANEL2, lightcolor=ACCENT,
                        darkcolor=ACCENT)
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", PANEL)],
                  foreground=[("active", TEXT)])
        style.configure("TEntry", foreground=TEXT, insertcolor=TEXT)
        style.configure("TCombobox", foreground=TEXT, fieldbackground=PANEL2,
                        background=PANEL2, arrowcolor=TEXT)
        style.configure("TSpinbox", foreground=TEXT, fieldbackground=PANEL2,
                        arrowcolor=TEXT)

    # ------------------------------------------------------------------ #
    # Интерфейс
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        # --- Верхняя панель ---
        top = tk.Frame(self.root, bg=BG, pady=10, padx=14)
        top.pack(fill="x")
        tk.Label(top, text="🚆 MaDaDev RTS — Лаунчер", bg=BG, fg=TEXT,
                 font=("Segoe UI", 15, "bold")).pack(side="left")
        self.btn_refresh = ttk.Button(top, text="⟳ Обновить каталог",
                                      command=self.refresh_catalog)
        self.btn_refresh.pack(side="right", padx=(8, 0))
        self.btn_open_folder = ttk.Button(top, text="📂 Папка игры",
                                          command=self.open_game_folder)
        self.btn_open_folder.pack(side="right", padx=(8, 0))
        self.btn_launch = ttk.Button(top, text="▶ Запустить игру",
                                     style="Accent.TButton", command=self.launch_game)
        self.btn_launch.pack(side="right", padx=(8, 0))

        # --- Вкладки ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        self.tab_catalog = ttk.Frame(self.notebook, padding=10)
        self.tab_installed = ttk.Frame(self.notebook, padding=10)
        self.tab_settings = ttk.Frame(self.notebook, padding=10)
        self.tab_log = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_catalog, text="  📦 Каталог  ")
        self.notebook.add(self.tab_installed, text="  ✅ Установленные  ")
        self.notebook.add(self.tab_settings, text="  ⚙ Настройки  ")
        self.notebook.add(self.tab_log, text="  📜 Журнал  ")

        self._build_catalog_tab()
        self._build_installed_tab()
        self._build_settings_tab()
        self._build_log_tab()

        # --- Нижняя панель: прогресс + статус ---
        bottom = tk.Frame(self.root, bg=BG, pady=8, padx=14)
        bottom.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, mode="determinate", length=320)
        self.progress.pack(side="left")
        self.status_var = tk.StringVar(value="Готово")
        tk.Label(bottom, textvariable=self.status_var, bg=BG, fg=MUTED,
                 anchor="w", font=("Segoe UI", 9)).pack(side="left", padx=12)

    # --- Каталог ---
    def _build_catalog_tab(self) -> None:
        bar = tk.Frame(self.tab_catalog, bg=PANEL)
        bar.pack(fill="x", pady=(0, 8))

        tk.Label(bar, text="Поиск:", bg=PANEL, fg=MUTED).pack(side="left", padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._render_catalog())
        search = ttk.Entry(bar, textvariable=self.search_var, width=26)
        search.pack(side="left")

        tk.Label(bar, text="  Тип:", bg=PANEL, fg=MUTED).pack(side="left", padx=(12, 6))
        self.type_var = tk.StringVar(value=TYPE_FILTERS[0][1])
        type_box = ttk.Combobox(bar, textvariable=self.type_var, state="readonly",
                                values=[label for _, label in TYPE_FILTERS],
                                width=14)
        type_box.pack(side="left")
        type_box.bind("<<ComboboxSelected>>", lambda *_: self._render_catalog())

        self.btn_install_sel = ttk.Button(bar, text="⬇ Установить выбранное",
                                          command=self._install_selected)
        self.btn_install_sel.pack(side="right", padx=(8, 0))
        self.btn_install_all = ttk.Button(bar, text="⬇ Установить всё",
                                          style="Accent.TButton",
                                          command=self._install_all)
        self.btn_install_all.pack(side="right")

        cols = ("name", "type", "version", "size", "status")
        self.cat_tree = ttk.Treeview(self.tab_catalog, columns=cols,
                                     show="headings", selectmode="extended")
        headers = {
            "name": ("Название", 320),
            "type": ("Тип", 110),
            "version": ("Версия", 90),
            "size": ("Размер", 90),
            "status": ("Статус", 170),
        }
        for cid, (title, width) in headers.items():
            self.cat_tree.heading(cid, text=title)
            self.cat_tree.column(cid, width=width, anchor="w")
        self.cat_tree.tag_configure("installed", foreground=OK)
        self.cat_tree.tag_configure("update", foreground=WARN)
        cat_scroll = ttk.Scrollbar(self.tab_catalog, orient="vertical",
                                   command=self.cat_tree.yview)
        self.cat_tree.configure(yscrollcommand=cat_scroll.set)
        self.cat_tree.pack(side="left", fill="both", expand=True)
        cat_scroll.pack(side="left", fill="y", padx=(6, 0))
        self.cat_tree.bind("<Double-1>", lambda _e: self._install_selected())

        hint = ("Подсказка: при установке карты, сценария или мода лаунчер "
                "автоматически подтянет все их дополнения и зависимости.")
        ttk.Label(self.tab_catalog, text=hint, style="Muted.TLabel",
                  wraplength=520).pack(anchor="w", pady=(8, 0))

    # --- Установленные ---
    def _build_installed_tab(self) -> None:
        bar = tk.Frame(self.tab_installed, bg=PANEL)
        bar.pack(fill="x", pady=(0, 8))

        self.btn_check_updates = ttk.Button(bar, text="🔍 Проверить обновления",
                                            command=self._check_updates)
        self.btn_check_updates.pack(side="left")
        self.btn_local_archive = ttk.Button(bar, text="📥 Установить из архива…",
                                            command=self.install_from_archive)
        self.btn_local_archive.pack(side="left", padx=(8, 0))
        self.btn_local_folder = ttk.Button(bar, text="📁 Установить из папки…",
                                           command=self.install_from_folder)
        self.btn_local_folder.pack(side="left", padx=(8, 0))
        self.btn_uninstall = ttk.Button(bar, text="🗑 Удалить выбранное",
                                        style="Danger.TButton",
                                        command=self._uninstall_selected)
        self.btn_uninstall.pack(side="right")
        self.btn_update_sel = ttk.Button(bar, text="⬆ Обновить выбранное",
                                         command=self._update_selected)
        self.btn_update_sel.pack(side="right", padx=(0, 8))

        cols = ("name", "type", "version", "date")
        self.inst_tree = ttk.Treeview(self.tab_installed, columns=cols,
                                      show="headings", selectmode="extended")
        for cid, title, width in (
            ("name", "Название", 340),
            ("type", "Тип", 120),
            ("version", "Установлено", 110),
            ("date", "Дата", 170),
        ):
            self.inst_tree.heading(cid, text=title)
            self.inst_tree.column(cid, width=width, anchor="w")
        inst_scroll = ttk.Scrollbar(self.tab_installed, orient="vertical",
                                    command=self.inst_tree.yview)
        self.inst_tree.configure(yscrollcommand=inst_scroll.set)
        self.inst_tree.pack(side="left", fill="both", expand=True)
        inst_scroll.pack(side="left", fill="y", padx=(6, 0))

        ttk.Label(self.tab_installed,
                  text="Пакеты стоят в папке игры; здесь видно, что установлено "
                       "и что можно обновить.",
                  style="Muted.TLabel", wraplength=520).pack(anchor="w", pady=(8, 0))

    # --- Настройки ---
    def _build_settings_tab(self) -> None:
        pad = {"padx": 4, "pady": 5}
        row = 0

        ttk.Label(self.tab_settings, text="Папка с игрой (куда ставить карты и моды):")\
            .grid(row=row, column=0, sticky="w", **pad)
        self.game_dir_var = tk.StringVar(value=self.cfg.get("game_dir") or "")
        ttk.Entry(self.tab_settings, textvariable=self.game_dir_var, width=64)\
            .grid(row=row, column=1, sticky="we", **pad)
        ttk.Button(self.tab_settings, text="Обзор…",
                   command=self._browse_game_dir).grid(row=row, column=2, **pad)
        row += 1

        ttk.Label(self.tab_settings, text="Файл игры (.exe):")\
            .grid(row=row, column=0, sticky="w", **pad)
        self.game_exe_var = tk.StringVar(value=self.cfg.get("game_exe") or "")
        ttk.Entry(self.tab_settings, textvariable=self.game_exe_var, width=64)\
            .grid(row=row, column=1, sticky="we", **pad)
        ttk.Button(self.tab_settings, text="Обзор…",
                   command=self._browse_game_exe).grid(row=row, column=2, **pad)
        row += 1

        ttk.Label(self.tab_settings, text="Зеркала репозитория:")\
            .grid(row=row, column=0, sticky="nw", **pad)
        mirror_frame = tk.Frame(self.tab_settings, bg=PANEL)
        mirror_frame.grid(row=row, column=1, sticky="we", **pad)
        self.mirror_list = tk.Listbox(mirror_frame, height=6, bg=PANEL2, fg=TEXT,
                                      selectbackground=ACCENT, relief="flat",
                                      highlightthickness=0, font=("Consolas", 10))
        self.mirror_list.pack(side="left", fill="both", expand=True)
        mirror_btns = tk.Frame(mirror_frame, bg=PANEL)
        mirror_btns.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(mirror_btns, text="+ Добавить",
                   command=self._add_mirror).pack(fill="x", pady=2)
        ttk.Button(mirror_btns, text="− Удалить",
                   command=self._remove_mirror).pack(fill="x", pady=2)
        ttk.Button(mirror_btns, text="Сделать активным",
                   command=self._activate_mirror).pack(fill="x", pady=2)
        row += 1

        ttk.Label(self.tab_settings,
                  text="Зеркало — это папка с manifest.json или URL вида "
                       "https://host/repo. Активное зеркало пробуется первым.",
                  style="Muted.TLabel", wraplength=560)\
            .grid(row=row, column=1, sticky="w", **pad)
        row += 1

        self.demo_var = tk.BooleanVar(value=bool(self.cfg.get("use_demo_repo")))
        ttk.Checkbutton(
            self.tab_settings,
            text="Демо-каталог-заглушка (только для проверки лаунчера, "
                 "не для игры; по умолчанию выключен)",
            variable=self.demo_var,
            command=self._toggle_demo,
        ).grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1

        self.auto_addons_var = tk.BooleanVar(value=bool(self.cfg.get("auto_addons")))
        ttk.Checkbutton(
            self.tab_settings,
            text="Автоматически подтягивать все дополнения и зависимости пакетов",
            variable=self.auto_addons_var,
            command=self._toggle_auto_addons,
        ).grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1

        actions = tk.Frame(self.tab_settings, bg=PANEL)
        actions.grid(row=row, column=0, columnspan=3, sticky="we", pady=(10, 0))
        ttk.Button(actions, text="💾 Сохранить настройки",
                   style="Accent.TButton",
                   command=self._save_settings).pack(side="left")
        ttk.Button(actions, text="Очистить кеш загрузок",
                   command=self._clear_cache).pack(side="left", padx=(10, 0))
        row += 1

        self.tab_settings.columnconfigure(1, weight=1)

    # --- Журнал ---
    def _build_log_tab(self) -> None:
        self.log_text = ScrolledText(self.tab_log, bg=PANEL, fg=TEXT,
                                     insertbackground=TEXT, relief="flat",
                                     font=("Consolas", 10), state="disabled")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("warn", foreground=WARN)
        self.log_text.tag_configure("err", foreground=ERR)
        self.log_text.tag_configure("ok", foreground=OK)
        self.log_text.tag_configure("muted", foreground=MUTED)

    # ------------------------------------------------------------------ #
    # Клиент репозитория / настройки
    # ------------------------------------------------------------------ #
    def effective_mirrors(self) -> list:
        mirrors = []
        if self.cfg.get("use_demo_repo"):
            try:
                mirrors.append(ensure_demo_repo(os.path.join(BASE_DIR, "demo_repo")))
            except Exception as exc:  # noqa: BLE001
                self.log(f"Не удалось создать демо-репозиторий: {exc}", "warn")
        mirrors.extend([m for m in (self.cfg.get("mirrors") or []) if m])
        return mirrors

    def rebuild_client(self) -> None:
        mirrors = self.effective_mirrors()
        self.client = RepoClient(mirrors, timeout=int(self.cfg.get("timeout") or 30))
        try:
            self.client.set_active(int(self.cfg.get("active_mirror") or 0))
        except (TypeError, ValueError):
            self.client.set_active(0)
        self.installer = Installer(self.cfg.get("game_dir") or "")
        self._render_mirror_list()

    def _render_mirror_list(self) -> None:
        self.mirror_list.delete(0, "end")
        active = int(self.cfg.get("active_mirror") or 0)
        for idx, mirror in enumerate(self.effective_mirrors()):
            label = "🧪 демо (офлайн)" if idx == 0 and self.cfg.get("use_demo_repo") else mirror
            if idx == active:
                label = "● " + label
            self.mirror_list.insert("end", label)

    def _browse_game_dir(self) -> None:
        path = filedialog.askdirectory(title="Выбери папку с игрой")
        if path:
            self.game_dir_var.set(path)

    def _browse_game_exe(self) -> None:
        path = filedialog.askopenfilename(
            title="Выбери файл игры",
            filetypes=[("Игры", "*.exe"), ("Все файлы", "*.*")],
        )
        if path:
            self.game_exe_var.set(path)

    def _add_mirror(self) -> None:
        value = simpledialog.askstring(
            "Новое зеркало",
            "URL репозитория или путь к папке с manifest.json:",
            parent=self.root,
        )
        if value and value.strip():
            mirrors = list(self.cfg.get("mirrors") or [])
            mirrors.append(value.strip())
            self.cfg.set("mirrors", mirrors)
            self.rebuild_client()
            self.log(f"Зеркало добавлено: {value.strip()}")

    def _remove_mirror(self) -> None:
        sel = self.mirror_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx == 0 and self.cfg.get("use_demo_repo"):
            messagebox.showinfo(APP_TITLE, "Демо-зеркало убирается галочкой "
                               "«Встроенный демо-каталог».", parent=self.root)
            return
        offset = 1 if self.cfg.get("use_demo_repo") else 0
        mirrors = list(self.cfg.get("mirrors") or [])
        pos = idx - offset
        if 0 <= pos < len(mirrors):
            removed = mirrors.pop(pos)
            self.cfg.set("mirrors", mirrors)
            if int(self.cfg.get("active_mirror") or 0) >= len(self.effective_mirrors()):
                self.cfg.set("active_mirror", 0)
            self.rebuild_client()
            self.log(f"Зеркало удалено: {removed}")

    def _activate_mirror(self) -> None:
        sel = self.mirror_list.curselection()
        if not sel:
            return
        self.cfg.set("active_mirror", int(sel[0]))
        self.rebuild_client()
        active = self.client.active_mirror
        self.log(f"Активное зеркало: {active}", "ok")

    def _toggle_demo(self) -> None:
        self.cfg.set("use_demo_repo", bool(self.demo_var.get()))
        self.cfg.save()
        self.rebuild_client()
        self.refresh_catalog()

    def _toggle_auto_addons(self) -> None:
        self.cfg.set("auto_addons", bool(self.auto_addons_var.get()))
        self.cfg.save()
        state = "включено" if self.cfg.get("auto_addons") else "выключено"
        self.log(f"Авто-подтягивание дополнений: {state}")

    def _save_settings(self) -> None:
        self.cfg.set("game_dir", self.game_dir_var.get().strip())
        self.cfg.set("game_exe", self.game_exe_var.get().strip())
        self.cfg.save()
        self.rebuild_client()
        self.refresh_catalog()
        self._refresh_installed()
        self.log("Настройки сохранены.", "ok")

    def _clear_cache(self) -> None:
        if not self.installer.ready:
            messagebox.showwarning(APP_TITLE, "Сначала укажи папку с игрой.",
                                   parent=self.root)
            return
        freed = self.installer.clear_cache()
        self.log(f"Кеш очищен, освобождено {fmt_size(freed)}.", "ok")

    # ------------------------------------------------------------------ #
    # Каталог / установленные
    # ------------------------------------------------------------------ #
    def refresh_catalog(self) -> None:
        if self.job_running:
            self.log("Дождись окончания текущей установки.", "warn")
            return
        self.status_var.set("Загрузка каталога…")
        self.btn_refresh.state(["disabled"])
        threading.Thread(target=self._catalog_worker, daemon=True).start()

    def _catalog_worker(self) -> None:
        try:
            manifest = load_manifest(self.client)
            self.q.put(("catalog", manifest))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("catalog_error", str(exc)))

    def _render_catalog(self) -> None:
        tree = self.cat_tree
        children = tree.get_children()
        if children:
            tree.delete(*children)
        if not self.manifest:
            return
        needle = self.search_var.get().strip().lower()
        wanted_label = self.type_var.get()
        wanted_type = "all"
        for key, label in TYPE_FILTERS:
            if label == wanted_label:
                wanted_type = key
                break
        for pkg in self.manifest.packages:
            if wanted_type != "all" and pkg.type != wanted_type:
                continue
            if needle and needle not in pkg.name.lower() and needle not in pkg.id.lower():
                continue
            status = self.installer.status_label(pkg)
            tags = ()
            if status == "Установлено":
                tags = ("installed",)
            elif status == "Есть обновление":
                tags = ("update",)
            tree.insert("", "end", iid=pkg.id,
                        values=(pkg.name, pkg.type_label, pkg.version,
                                fmt_size(pkg.size), status),
                        tags=tags)

    def _refresh_installed(self) -> None:
        tree = self.inst_tree
        children = tree.get_children()
        if children:
            tree.delete(*children)
        entries = self.installer.installed() if self.installer.ready else {}
        for pid, entry in sorted(entries.items(), key=lambda kv: kv[1].get("name", kv[0])):
            ptype = str(entry.get("type") or "mod")
            tree.insert("", "end", iid=pid,
                        values=(entry.get("name") or pid,
                                TYPE_LABELS.get(ptype, ptype),
                                entry.get("version") or "?",
                                (entry.get("installed_at") or "")[:10]))

    # ------------------------------------------------------------------ #
    # Установка
    # ------------------------------------------------------------------ #
    def _selected_catalog_ids(self) -> list:
        return list(self.cat_tree.selection())

    def _install_selected(self) -> None:
        ids = self._selected_catalog_ids()
        if not ids:
            messagebox.showinfo(APP_TITLE, "Выбери пакеты в каталоге (клик/двойной клик).",
                                parent=self.root)
            return
        self._start_install(ids, f"Установка выбранных пакетов ({len(ids)})")

    def _install_all(self) -> None:
        if not self.manifest:
            return
        ids = [p.id for p in self.manifest.packages]
        self._start_install(ids, f"Установка всех пакетов ({len(ids)})")

    def _update_selected(self) -> None:
        ids = list(self.inst_tree.selection())
        if not ids:
            messagebox.showinfo(APP_TITLE, "Выбери пакеты в списке установленных.",
                                parent=self.root)
            return
        self._start_install(ids, f"Обновление выбранных пакетов ({len(ids)})")

    def _start_install(self, ids, title: str) -> None:
        if self.job_running:
            return
        if not self.manifest:
            messagebox.showwarning(APP_TITLE, "Каталог ещё не загружен — нажми "
                                   "«Обновить каталог».", parent=self.root)
            return
        if not self.installer.ready:
            messagebox.showwarning(APP_TITLE, "Сначала укажи папку с игрой "
                                   "во вкладке «Настройки».", parent=self.root)
            self.notebook.select(self.tab_settings)
            return
        self.job_cancel.clear()
        self.job_running = True
        self._set_busy(True)
        self.log(f"— {title} —", "muted")
        manifest = self.manifest
        threading.Thread(target=self._install_worker,
                         args=(manifest, list(ids)), daemon=True).start()

    def _install_worker(self, manifest: Manifest, requested: list) -> None:
        q = self.q
        try:
            auto_addons = bool(self.cfg.get("auto_addons"))
            packages, pulled, missing = resolve(
                manifest, requested, auto_addons=auto_addons
            )
            by_id = manifest.by_id()
            for mid in missing:
                q.put(("log", f"⚠ Нет в каталоге: {mid}", "warn"))
            for pid in pulled:
                pkg = by_id[pid]
                q.put(("log",
                       f"↳ Подтягиваю автоматически: {pkg.name} "
                       f"({pkg.type_label}, {pkg.version})"))
            if not packages:
                q.put(("job_done", False, "Нечего устанавливать — пакеты не найдены"))
                return

            todo = []
            for pkg in packages:
                if self.installer.status(pkg) == "installed":
                    q.put(("log", f"✓ Уже установлено: {pkg.name} {pkg.version}",
                           "muted"))
                else:
                    todo.append(pkg)
            if not todo:
                q.put(("job_done", True, "Всё уже установлено — обновлений нет"))
                return

            # --- Фаза 1: скачивание ---
            total = sum(max(p.size, 0) for p in todo) or 1
            done_bytes = 0
            q.put(("progress", 0, total, "Скачивание"))
            for pkg in todo:
                if self.job_cancel.is_set():
                    raise Cancelled()
                dest = self.installer.cache_path(pkg)
                if self.installer.is_cached(pkg):
                    done_bytes += pkg.size
                    q.put(("log", f"Из кеша: {pkg.name} {pkg.version}", "muted"))
                    q.put(("progress", min(done_bytes, total), total, "Скачивание"))
                    continue
                base = done_bytes
                q.put(("log", f"Скачиваю: {pkg.name} ({fmt_size(pkg.size)})"))

                def on_progress(done, _total, base=base, total=total):
                    q.put(("progress", min(base + done, total), total, "Скачивание"))

                self.client.download(
                    pkg.file, dest, sha256=pkg.sha256,
                    progress=on_progress,
                    cancel=self.job_cancel.is_set,
                )
                try:
                    done_bytes += os.path.getsize(dest)
                except OSError:
                    done_bytes += pkg.size
                q.put(("progress", min(done_bytes, total), total, "Скачивание"))

            # --- Фаза 2: установка в папку игры ---
            count = len(todo)
            for idx, pkg in enumerate(todo, 1):
                if self.job_cancel.is_set():
                    raise Cancelled()
                q.put(("progress", idx - 1, count, "Установка"))
                self.installer.install_package(pkg, self.installer.cache_path(pkg))
                q.put(("log", f"✓ Установлено: {pkg.name} {pkg.version}", "ok"))
            q.put(("progress", count, count, "Установка"))

            msg = f"Готово! Установлено пакетов: {count}"
            if pulled:
                msg += f" (из них подтянуто автоматически: {len(pulled)})"
            q.put(("job_done", True, msg))
        except Cancelled:
            q.put(("job_done", False, "Установка отменена"))
        except Exception as exc:  # noqa: BLE001
            q.put(("log", traceback.format_exc(), "err"))
            q.put(("job_done", False, f"Ошибка: {exc}"))

    def _check_updates(self) -> None:
        if not self.manifest:
            self.log("Каталог не загружен.", "warn")
            return
        if not self.installer.ready:
            self.log("Папка с игрой не указана.", "warn")
            return
        found = 0
        for pkg in self.manifest.packages:
            if self.installer.status(pkg) == "update":
                entry = self.installer.entry(pkg.id) or {}
                self.log(f"⬆ {pkg.name}: {entry.get('version', '?')} → {pkg.version}")
                found += 1
        if found:
            self.log(f"Доступно обновлений: {found}", "ok")
        else:
            self.log("Все установленные пакеты актуальны.", "ok")

    def _uninstall_selected(self) -> None:
        ids = list(self.inst_tree.selection())
        if not ids:
            messagebox.showinfo(APP_TITLE, "Выбери пакеты для удаления.",
                                parent=self.root)
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Удалить {len(ids)} пакет(ов) и их файлы из папки игры?",
            parent=self.root,
        ):
            return
        if self.job_running:
            return
        self.job_running = True
        self._set_busy(True)
        threading.Thread(target=self._uninstall_worker, args=(ids,),
                         daemon=True).start()

    def _uninstall_worker(self, ids: list) -> None:
        try:
            for pid in ids:
                if self.job_cancel.is_set():
                    self.q.put(("job_done", False, "Удаление отменено"))
                    return
                if self.installer.uninstall(pid):
                    self.q.put(("log", f"🗑 Удалено: {pid}", "ok"))
                else:
                    self.q.put(("log", f"⚠ Не найдено для удаления: {pid}", "warn"))
            self.q.put(("job_done", True, "Удаление завершено"))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("log", traceback.format_exc(), "err"))
            self.q.put(("job_done", False, f"Ошибка: {exc}"))

    # ------------------------------------------------------------------ #
    # Реальная установка из архивов и папок (без репозитория)
    # ------------------------------------------------------------------ #
    def install_from_archive(self) -> None:
        path = filedialog.askopenfilename(
            title="Выбери архив мода или карты (.zip)",
            filetypes=[("Архивы ZIP", "*.zip"), ("Все файлы", "*.*")],
            parent=self.root,
        )
        if path:
            self.install_local_package(path, kind="archive")

    def install_from_folder(self) -> None:
        path = filedialog.askdirectory(
            title="Выбери папку пакета (ROUTES / TRAINS / GLOBAL / SOUND)",
            parent=self.root,
        )
        if not path:
            return
        try:
            top = os.listdir(path)
        except OSError as exc:
            messagebox.showerror(APP_TITLE,
                                 f"Не удалось прочитать папку:\n{exc}",
                                 parent=self.root)
            return
        if not looks_like_game_tree(top):
            if not messagebox.askyesno(
                APP_TITLE,
                "В папке нет игровых каталогов (ROUTES, TRAINS, GLOBAL, "
                "SOUND, GUI).\nВсё равно установить её содержимое в папку игры?",
                parent=self.root,
            ):
                return
        self.install_local_package(path, kind="folder")

    def install_local_package(self, path: str, kind: str = "archive") -> None:
        """Поставить реальный пакет из .zip или папки — без репозитория."""
        if self.job_running:
            return
        if not self.installer.ready:
            messagebox.showwarning(
                APP_TITLE,
                "Сначала укажи папку с игрой во вкладке «Настройки».",
                parent=self.root,
            )
            self.notebook.select(self.tab_settings)
            return
        self.job_cancel.clear()
        self.job_running = True
        self._set_busy(True)
        label = os.path.basename(path.rstrip("/\\"))
        self.log(f"— Установка из {'архива' if kind == 'archive' else 'папки'}: "
                 f"{label} —", "muted")
        threading.Thread(target=self._local_install_worker,
                         args=(path, kind), daemon=True).start()

    def _local_install_worker(self, path: str, kind: str) -> None:
        q = self.q
        try:
            meta = read_package_meta(path)
            entry = self.installer.install_local(path, meta)
            src = "архива" if kind == "archive" else "папки"
            q.put(("log",
                   f"✓ Установлено из {src}: {entry['name']} "
                   f"({TYPE_LABELS.get(entry['type'], entry['type'])}, "
                   f"{entry['version']}) — файлов: {len(entry['files'])}", "ok"))
            q.put(("job_done", True,
                   f"Установлено: {entry['name']} {entry['version']}"))
        except Exception as exc:  # noqa: BLE001
            q.put(("log", traceback.format_exc(), "err"))
            q.put(("job_done", False, f"Ошибка установки: {exc}"))

    # ------------------------------------------------------------------ #
    # Запуск игры
    # ------------------------------------------------------------------ #
    def _find_game_exe(self, game_dir: str) -> str:
        for name in GAME_EXE_PREFERRED:
            path = os.path.join(game_dir, name)
            if os.path.isfile(path):
                return path
        try:
            for name in sorted(os.listdir(game_dir)):
                low = name.lower()
                if low.endswith(".exe") and not any(x in low for x in EXE_EXCLUDE):
                    return os.path.join(game_dir, name)
        except OSError:
            pass
        return ""

    def launch_game(self) -> None:
        game_dir = (self.game_dir_var.get().strip()
                    if hasattr(self, "game_dir_var")
                    else "") or (self.cfg.get("game_dir") or "")
        if not game_dir or not os.path.isdir(game_dir):
            messagebox.showwarning(APP_TITLE, "Сначала укажи папку с игрой "
                                   "во вкладке «Настройки».", parent=self.root)
            self.notebook.select(self.tab_settings)
            return
        exe = (self.cfg.get("game_exe") or "").strip()
        if not exe or not os.path.isfile(exe):
            exe = self._find_game_exe(game_dir)
        if not exe:
            messagebox.showwarning(
                APP_TITLE,
                "Не удалось найти .exe игры. Укажи его в настройках.",
                parent=self.root,
            )
            self.notebook.select(self.tab_settings)
            return
        if os.name != "nt":
            self.log("Игра запускается на Windows — здесь проверить не выйдет.", "warn")
        try:
            subprocess.Popen([exe], cwd=game_dir)
            self.log(f"Запускаю: {exe}", "ok")
            self.status_var.set("Игра запускается…")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Не удалось запустить игру:\n{exc}",
                                 parent=self.root)

    # ------------------------------------------------------------------ #
    # Служебное
    # ------------------------------------------------------------------ #
    @staticmethod
    def _apply_window_icon(root: "tk.Tk") -> None:
        """Иконка окна: из папки исходников либо из ресурсов exe."""
        candidates = (
            os.path.join(RESOURCE_DIR, "assets", "launcher.png"),
            os.path.join(RESOURCE_DIR, "launcher.png"),
        )
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                img = tk.PhotoImage(file=path)
                root.iconphoto(True, img)
                root._mdd_icon = img  # не давать GC убрать картинку
            except Exception:
                pass
            return

    def open_game_folder(self) -> None:
        game_dir = self.cfg.get("game_dir") or ""
        if not game_dir or not os.path.isdir(game_dir):
            messagebox.showwarning(APP_TITLE, "Папка с игрой не указана.",
                                   parent=self.root)
            self.notebook.select(self.tab_settings)
            return
        try:
            if os.name == "nt":
                os.startfile(game_dir)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", game_dir])
        except OSError as exc:
            self.log(f"Не удалось открыть папку: {exc}", "warn")

    def _set_busy(self, busy: bool) -> None:
        state = ["disabled"] if busy else ["!disabled"]
        for btn in (self.btn_install_sel, self.btn_install_all,
                    self.btn_update_sel, self.btn_uninstall,
                    self.btn_check_updates, self.btn_refresh,
                    self.btn_local_archive, self.btn_local_folder):
            btn.state(state)
        if busy:
            # Кнопка отмены подменяет «Обновить каталог» на время задачи
            if not hasattr(self, "_cancel_btn"):
                self._cancel_btn = ttk.Button(
                    self.btn_refresh.master, text="■ Отмена",
                    command=self._cancel_job,
                )
            self._cancel_btn.pack(side="right", padx=(8, 0))
            self.btn_refresh.pack_forget()
            self.btn_launch.state(["disabled"])
        else:
            if hasattr(self, "_cancel_btn"):
                self._cancel_btn.pack_forget()
            self.btn_refresh.pack(side="right", padx=(8, 0))
            self.btn_launch.state(["!disabled"])
            self.job_cancel.clear()

    def _cancel_job(self) -> None:
        if self.job_running:
            self.job_cancel.set()
            self.status_var.set("Отмена…")

    def log(self, text: str, tag: str | None = None) -> None:
        self.q.put(("log", text, tag))

    def _append_log(self, text: str, tag: str | None) -> None:
        widget = self.log_text
        widget.configure(state="normal")
        widget.insert("end", text.rstrip("\n") + "\n", tag or "")
        widget.see("end")
        widget.configure(state="disabled")

    def _poll(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append_log(msg[1], msg[2] if len(msg) > 2 else None)
                elif kind == "status":
                    self.status_var.set(msg[1])
                elif kind == "progress":
                    _, value, maximum, phase = msg
                    maximum = max(int(maximum), 1)
                    value = min(int(value), maximum)
                    self.progress.configure(maximum=maximum, value=value)
                    if phase == "Скачивание":
                        self.status_var.set(
                            f"Скачивание: {fmt_size(value)} из {fmt_size(maximum)}")
                    else:
                        self.status_var.set(f"Установка: {value}/{maximum}")
                elif kind == "catalog":
                    self.manifest = msg[1]
                    self._render_catalog()
                    self._refresh_installed()
                    n = len(self.manifest.packages)
                    self.status_var.set(
                        f"Каталог: {self.manifest.name} — пакетов: {n}")
                    self.log(f"Каталог загружен: {self.manifest.name} "
                             f"(пакетов: {n})", "ok")
                    self.btn_refresh.state(["!disabled"])
                elif kind == "catalog_error":
                    self.btn_refresh.state(["!disabled"])
                    self.status_var.set("Каталог недоступен")
                    self.log(f"Каталог недоступен: {msg[1]}", "err")
                    messagebox.showwarning(
                        APP_TITLE,
                        f"Не удалось загрузить каталог:\n{msg[1]}\n\n"
                        "Добавь зеркало во вкладке «Настройки» либо установи "
                        "пакет из архива/папки (вкладка «Установленные»).",
                        parent=self.root,
                    )
                elif kind == "job_done":
                    self.job_running = False
                    self._set_busy(False)
                    self.progress.configure(value=0)
                    ok, text = msg[1], msg[2]
                    self.status_var.set(text)
                    self.log(text, "ok" if ok else "warn")
                    self._render_catalog()
                    self._refresh_installed()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _on_close(self) -> None:
        try:
            self.cfg.set("window_geometry", self.root.geometry())
            self.cfg.save()
        except Exception:
            pass
        self.job_cancel.set()
        self.root.destroy()


def _log_uncaught(exc_type, exc, tb) -> None:
    """Необработанные ошибки — в stderr и launcher_error.log рядом с exe."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        sys.stderr.write(text)
    except Exception:
        pass
    try:
        with open(os.path.join(BASE_DIR, "launcher_error.log"), "a",
                  encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} "
                    f"=====\n{text}")
    except OSError:
        pass
    if exc_type in (SystemExit, KeyboardInterrupt):
        return
    try:
        import tkinter.messagebox as mb
        mb.showerror(
            APP_TITLE,
            f"Произошла непредвиденная ошибка:\n\n{exc}\n\n"
            "Подробности записаны в файл launcher_error.log "
            "рядом с лаунчером.",
        )
    except Exception:
        pass


def _install_error_handler() -> None:
    sys.excepthook = _log_uncaught

    def _thread_hook(args) -> None:
        _log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = _thread_hook


def main() -> None:
    _install_error_handler()
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
