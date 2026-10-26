"""Постоянная память Капри: кто пользователь, что он просил и что просил запомнить.

Всё хранится локально в data/memory.json и никуда не отправляется, кроме коротких выдержек,
которые попадают в подсказку нейросети (context()).

Важно: на один файл — один объект (MemoryStore.shared). Раньше у Actions и LocalAI были свои копии,
и они затирали друг другу записи; теперь все пользуются общей и перечитывают файл, если его поменяли.
"""
import datetime
import json
import os
import re
import threading

# Секреты в память не пишем: ключи API и длинные «токены» заменяются на маркер.
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{16,}|AIza[0-9A-Za-z_\-]{20,}|ghp_[A-Za-z0-9]{20,}|"
                       r"\b[A-Fa-f0-9]{32,}\b|\b[A-Za-z0-9_\-]{40,}\b)")

MAX_FACTS = 300
MAX_NOTES = 200


def _now():
    return datetime.datetime.now().isoformat(timespec="minutes")


def _clean(text, limit):
    text = SECRET_RE.sub("[секрет скрыт]", (text or "").strip())
    return re.sub(r"\s+", " ", text)[:limit]


def _words(text):
    return {w for w in re.findall(r"\w+", (text or "").lower().replace("ё", "е")) if len(w) > 2}


class MemoryStore:
    _shared = {}
    _shared_lock = threading.Lock()

    @classmethod
    def shared(cls, base_dir, retention=100):
        """Единый объект памяти на папку проекта."""
        key = os.path.realpath(base_dir)
        with cls._shared_lock:
            if key not in cls._shared:
                cls._shared[key] = cls(base_dir, retention)
            return cls._shared[key]

    def __init__(self, base_dir, retention=100):
        self.path = os.path.join(base_dir, "data", "memory.json")
        self.retention = max(10, int(retention))
        self.lock = threading.RLock()
        self._mtime = 0.0
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.data = self._empty()
        self._load()

    # ---------- файл ----------
    @staticmethod
    def _empty():
        return {"version": 2, "profile": {}, "requests": [], "notes": []}

    def _file_mtime(self):
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def _load(self):
        data = self._empty()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for k in ("profile", "requests", "notes"):
                    if isinstance(loaded.get(k), type(data[k])):
                        data[k] = loaded[k]
        except (OSError, ValueError):
            pass
        self.data = data
        self._mtime = self._file_mtime()

    def _refresh(self):
        """Файл могли поменять руками или другой процесс — перечитываем перед работой."""
        if self._file_mtime() != self._mtime:
            self._load()

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            self._mtime = self._file_mtime()

    # ---------- кто пользователь: факты ----------
    @property
    def profile(self):
        with self.lock:
            self._refresh()
            return dict(self.data["profile"])

    @property
    def requests(self):
        with self.lock:
            self._refresh()
            return list(self.data["requests"])

    def remember_fact(self, fact):
        """Запоминает факт о пользователе. Повтор того же факта не дублируется."""
        fact = _clean(fact, 500)
        if len(fact) < 3:
            return False
        with self.lock:
            self._refresh()
            profile = self.data["profile"]
            norm = fact.lower()
            if any(v.lower() == norm for v in profile.values()):
                return True
            key = fact[:80]
            while key in profile:  # ключи разных фактов не должны совпасть
                key += "·"
            profile[key] = fact
            while len(profile) > MAX_FACTS:  # самые старые выпадают первыми
                del profile[next(iter(profile))]
            self.save()
        return True

    def forget_fact(self, key):
        key = (key or "").strip().lower()
        if not key:
            return 0
        with self.lock:
            self._refresh()
            profile = self.data["profile"]
            found = [k for k, v in profile.items() if key in k.lower() or key in v.lower()]
            for k in found:
                del profile[k]
            if found:
                self.save()
            return len(found)

    # ---------- что просил: история запросов ----------
    def log_turn(self, question, answer):
        question = _clean(question, 1000)
        if not question:
            return
        with self.lock:
            self._refresh()
            rows = self.data["requests"]
            rows.append({"at": _now(), "request": question, "answer": _clean(answer, 1500)})
            self.data["requests"] = rows[-self.retention:]
            self.save()

    def clear_requests(self):
        with self.lock:
            self._refresh()
            n = len(self.data["requests"])
            self.data["requests"] = []
            self.save()
            return n

    # ---------- заметки и дела ----------
    def add_note(self, text):
        text = _clean(text, 500)
        if not text:
            return None
        with self.lock:
            self._refresh()
            notes = self.data["notes"]
            nid = max([n.get("id", 0) for n in notes] + [0]) + 1
            notes.append({"id": nid, "at": _now(), "text": text, "done": False})
            self.data["notes"] = notes[-MAX_NOTES:]
            self.save()
            return nid

    def notes(self, open_only=True):
        with self.lock:
            self._refresh()
            return [dict(n) for n in self.data["notes"] if not (open_only and n.get("done"))]

    def finish_note(self, key):
        """Отмечает дело выполненным: по номеру или по кусочку текста."""
        key = str(key).strip().lower().lstrip("#№")
        with self.lock:
            self._refresh()
            hit = 0
            for n in self.data["notes"]:
                if n.get("done"):
                    continue
                if key == str(n.get("id")) or (len(key) > 2 and key in n.get("text", "").lower()):
                    n["done"] = True
                    hit += 1
            if hit:
                self.save()
            return hit

    def remove_notes(self, key):
        key = str(key).strip().lower().lstrip("#№")
        with self.lock:
            self._refresh()
            keep = [n for n in self.data["notes"]
                    if not (key == str(n.get("id")) or (len(key) > 2 and key in n.get("text", "").lower()))]
            removed = len(self.data["notes"]) - len(keep)
            if removed:
                self.data["notes"] = keep
                self.save()
            return removed

    # ---------- поиск и подсказка для нейросети ----------
    def search(self, query, limit=5):
        """Что я знаю по теме: факты и прошлые запросы, лучшие совпадения по словам."""
        q = _words(query)
        if not q:
            return []
        with self.lock:
            self._refresh()
            scored = []
            for v in self.data["profile"].values():
                s = len(q & _words(v))
                if s:
                    scored.append((s + 1, "факт: " + v))
            for r in self.data["requests"]:
                s = len(q & _words(r.get("request", "") + " " + r.get("answer", "")))
                if s:
                    scored.append((s, f"{r.get('at', '')[:10]} просил: {r.get('request', '')[:200]}"))
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored[:limit]]

    def context(self, query=None):
        """Короткая выдержка для подсказки нейросети: факты о пользователе, недавние запросы, дела."""
        with self.lock:
            self._refresh()
            profile = list(self.data["profile"].values())
            requests = self.data["requests"]
            todo = [n for n in self.data["notes"] if not n.get("done")]
        bits = []
        if profile:
            text, size = [], 0
            for fact in reversed(profile):  # свежие факты важнее
                if size + len(fact) > 2500:
                    break
                text.append(fact)
                size += len(fact) + 2
            bits.append("Что известно о пользователе (он сам попросил запомнить): " + "; ".join(reversed(text)))
        if requests:
            bits.append("Недавние запросы (для контекста, не повторяй их сама): " +
                        "; ".join(x.get("request", "")[:150] for x in requests[-5:]))
        if query:
            older = [t for t in self.search(query, 3) if t.startswith(tuple("0123456789"))]
            if older:
                bits.append("Похожее из прошлых разговоров: " + "; ".join(older))
        if todo:
            bits.append("Открытые дела пользователя: " + "; ".join(n["text"][:100] for n in todo[:8]))
        return "\n".join(bits)

    def summary(self):
        with self.lock:
            self._refresh()
            return (len(self.data["profile"]), len(self.data["requests"]),
                    len([n for n in self.data["notes"] if not n.get("done")]))
