# -*- coding: utf-8 -*-
"""Минимальная заглушка tkinter для headless-тестов GUI лаунчера.

Позволяет импортировать и прогнать ``main.py`` без дисплея и без
установленного tkinter: проверяется логика окна (каталог, установка,
настройки, журнал), а не рисование.
"""

from __future__ import annotations

import sys
import types


class TclError(Exception):
    pass


class _Var:
    def __init__(self, master=None, value=None, name=None):
        # Как в настоящем tkinter: значение по умолчанию — пустая строка
        self._value = "" if value is None else value
        self._traces = []

    def get(self):
        return self._value

    def set(self, value):
        self._value = value

    def trace_add(self, *args, **kwargs):
        self._traces.append((args, kwargs))


class StringVar(_Var):
    pass


class BooleanVar(_Var):
    pass


class Widget:
    def __init__(self, master=None, **kwargs):
        self.master = master
        self.kwargs = kwargs
        self.children = []
        if master is not None and hasattr(master, "children"):
            master.children.append(self)

    # layout
    def pack(self, *args, **kwargs):
        pass

    def pack_forget(self, *args, **kwargs):
        pass

    def grid(self, *args, **kwargs):
        pass

    def grid_forget(self, *args, **kwargs):
        pass

    def columnconfigure(self, *args, **kwargs):
        pass

    def rowconfigure(self, *args, **kwargs):
        pass

    # common
    def configure(self, *args, **kwargs):
        pass

    config = configure

    def bind(self, *args, **kwargs):
        pass

    def state(self, *args, **kwargs):
        pass

    def focus(self, *args, **kwargs):
        pass

    def yview(self, *args, **kwargs):
        pass

    def xview(self, *args, **kwargs):
        pass

    def set(self, *args, **kwargs):
        pass


class Button(Widget):
    def __init__(self, master=None, command=None, **kwargs):
        super().__init__(master, **kwargs)
        self.command = command

    def invoke(self):
        if self.command:
            return self.command()


class Treeview(Widget):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._rows = {}
        self._selection = []

    def heading(self, *args, **kwargs):
        pass

    def column(self, *args, **kwargs):
        pass

    def tag_configure(self, *args, **kwargs):
        pass

    def insert(self, parent, index, iid=None, values=(), tags=(), **kwargs):
        key = iid or f"item{len(self._rows)}"
        self._rows[key] = {"values": tuple(values), "tags": tuple(tags)}
        return key

    def get_children(self):
        return tuple(self._rows)

    def delete(self, *iids):
        if not iids:
            self._rows.clear()
            return
        for iid in iids:
            self._rows.pop(iid, None)

    def selection(self):
        return list(self._selection)

    def selection_set(self, items):
        self._selection = list(items)


class Listbox(Widget):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._items = []
        self._selection = []

    def insert(self, index, value):
        self._items.append(value)

    def delete(self, first, last=None):
        if last in (None, "end") or first == 0 and last == "end":
            self._items.clear()
        else:
            self._items = []

    def curselection(self):
        return tuple(self._selection)


class Text(Widget):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.content = []

    def insert(self, index, text, *tags):
        self.content.append((text, tags))

    def see(self, *args, **kwargs):
        pass

    def tag_configure(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        return "".join(t for t, _ in self.content)


class Progressbar(Widget):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.value = 0
        self.maximum = 100

    def configure(self, *args, **kwargs):
        if "value" in kwargs:
            self.value = kwargs["value"]
        if "maximum" in kwargs:
            self.maximum = kwargs["maximum"]


class Notebook(Widget):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.tabs = []
        self.current = None

    def add(self, tab, **kwargs):
        self.tabs.append(tab)

    def select(self, tab=None):
        if tab is not None:
            self.current = tab


class Style:
    def __init__(self, master=None):
        self.master = master

    def theme_use(self, *args, **kwargs):
        pass

    def configure(self, *args, **kwargs):
        pass

    def map(self, *args, **kwargs):
        pass


class Entry(Widget):
    pass


class Combobox(Entry):
    pass


class Checkbutton(Widget):
    pass


class Scrollbar(Widget):
    pass


class Frame(Widget):
    pass


class Label(Widget):
    pass


class Tk:
    def __init__(self):
        self.children = []
        self._geometry = "100x100"
        self._after = []
        self.destroyed = False
        self.title_text = ""

    def title(self, text=None):
        if text is not None:
            self.title_text = text
        return self.title_text

    def geometry(self, value=None):
        if value is None:
            return self._geometry
        self._geometry = value

    def minsize(self, *args, **kwargs):
        pass

    def configure(self, *args, **kwargs):
        pass

    def protocol(self, *args, **kwargs):
        pass

    def after(self, ms, func=None, *args):
        if func is not None:
            self._after.append((ms, func, args))
        return "after-id"

    def mainloop(self, *args, **kwargs):
        pass

    def destroy(self):
        self.destroyed = True


# --- messagebox / filedialog / simpledialog ---------------------------------
messagebox_calls = []


def _msg(name):
    def fn(*args, **kwargs):
        messagebox_calls.append((name, args, kwargs))
        if name == "askyesno":
            return True
        if name == "askokcancel":
            return True
        return "ok"

    fn.__name__ = name
    return fn


filedialog_calls = []


def _filedialog(name, result=""):
    def fn(*args, **kwargs):
        filedialog_calls.append((name, args, kwargs))
        return result

    fn.__name__ = name
    return fn


def install():
    """Зарегистрировать заглушку в sys.modules. Вернуть модуль tkinter."""
    tk = types.ModuleType("tkinter")
    ttk = types.ModuleType("tkinter.ttk")
    filedialog = types.ModuleType("tkinter.filedialog")
    messagebox = types.ModuleType("tkinter.messagebox")
    simpledialog = types.ModuleType("tkinter.simpledialog")
    scrolledtext = types.ModuleType("tkinter.scrolledtext")

    # tkinter.*
    tk.TclError = TclError
    tk.Tk = Tk
    tk.Widget = Widget
    tk.Frame = Frame
    tk.Label = Label
    tk.Text = Text
    tk.Listbox = Listbox
    tk.StringVar = StringVar
    tk.BooleanVar = BooleanVar
    tk.END = "end"

    # ttk.*
    ttk.Widget = Widget
    ttk.Frame = Frame
    ttk.Label = Label
    ttk.Button = Button
    ttk.Entry = Entry
    ttk.Combobox = Combobox
    ttk.Checkbutton = Checkbutton
    ttk.Scrollbar = Scrollbar
    ttk.Treeview = Treeview
    ttk.Notebook = Notebook
    ttk.Progressbar = Progressbar
    ttk.Style = Style

    # filedialog
    filedialog.askdirectory = _filedialog("askdirectory")
    filedialog.askopenfilename = _filedialog("askopenfilename")
    filedialog.askdirectory_calls = filedialog_calls

    # messagebox
    for name in ("showinfo", "showwarning", "showerror", "askyesno",
                 "askokcancel", "askretrycancel"):
        setattr(messagebox, name, _msg(name))

    # simpledialog
    simpledialog.askstring = _msg("askstring")
    # askstring должен возвращать None по умолчанию (пользователь отменил)
    simpledialog.askstring = lambda *a, **k: (
        filedialog_calls.append(("askstring", a, k)) or None
    )

    # scrolledtext
    scrolledtext.ScrolledText = Text

    tk.ttk = ttk
    tk.filedialog = filedialog
    tk.messagebox = messagebox
    tk.simpledialog = simpledialog
    tk.scrolledtext = scrolledtext

    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.messagebox"] = messagebox
    sys.modules["tkinter.simpledialog"] = simpledialog
    sys.modules["tkinter.scrolledtext"] = scrolledtext
    return tk
