"""Прогресс по сетке в той же Google-таблице, что и ритуал (три новых листа).

harada_tasks  — slot_id | задача | шагов | сделано | обновлено   (одна строка на задачу)
harada_habits — date | R1 … R11                                  (одна строка на день, 1 = сделано)
harada_focus  — date | focus | done                              (задачи дня из /today)

Всё читается в память при старте и пишется сразу при каждом изменении.
Без GOOGLE_CREDS_JSON / SPREADSHEET_ID работает только в памяти (для локальной проверки).
"""
from __future__ import annotations

import datetime as dt
import logging
import threading

from . import core

log = logging.getLogger(__name__)

TASKS_WS, HABITS_WS, FOCUS_WS = "harada_tasks", "harada_habits", "harada_focus"


class HaradaStore:
    def __init__(self, grid: dict, spreadsheet=None):
        self.grid = grid
        self.ss = spreadsheet
        self.lock = threading.Lock()
        self.codes = [h["code"] for h in core.habits(grid)]
        self.prog = core.Progress()
        self.focus: dict[str, dict] = {}       # date -> {"ids": [...], "done": set()}
        self._task_row: dict[str, int] = {}    # slot_id -> номер строки в листе
        self._habit_row: dict[str, int] = {}   # date -> номер строки
        self._focus_row: dict[str, int] = {}
        self.ws = {}
        if self.ss is not None:
            self._load()

    # ---------- листы ----------
    def _sheet(self, title: str, header: list[str], rows: int = 400):
        import gspread
        try:
            ws = self.ss.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.ss.add_worksheet(title=title, rows=rows, cols=max(len(header), 5))
            ws.append_row(header)
        return ws

    def _load(self):
        tasks = core.tasks(self.grid)
        self.ws[TASKS_WS] = ws = self._sheet(TASKS_WS, ["slot_id", "задача", "шагов", "сделано", "обновлено"], rows=80)
        values = ws.get_all_values()
        known = {}
        for i, row in enumerate(values[1:], start=2):
            if row and row[0]:
                known[row[0]] = i
                try:
                    self.prog.task_done[row[0]] = int(row[3] or 0)
                except (ValueError, IndexError):
                    self.prog.task_done[row[0]] = 0
        missing = [t for t in tasks if t["id"] not in known]
        if missing:
            ws.append_rows([[t["id"], t["text"], t["steps"], 0, ""] for t in missing])
            values = ws.get_all_values()
            known = {row[0]: i for i, row in enumerate(values[1:], start=2) if row and row[0]}
        self._task_row = known

        self.ws[HABITS_WS] = ws = self._sheet(HABITS_WS, ["date"] + self.codes)
        values = ws.get_all_values()
        header = values[0] if values else ["date"] + self.codes
        for i, row in enumerate(values[1:], start=2):
            if not row or not row[0]:
                continue
            self._habit_row[row[0]] = i
            self.prog.habit_log[row[0]] = {header[c] for c in range(1, min(len(row), len(header))) if row[c].strip() in ("1", "✓", "x", "TRUE")}
        self._habit_header = header

        self.ws[FOCUS_WS] = ws = self._sheet(FOCUS_WS, ["date", "focus", "done"])
        for i, row in enumerate(ws.get_all_values()[1:], start=2):
            if row and row[0]:
                self._focus_row[row[0]] = i
                self.focus[row[0]] = {"ids": [x for x in (row[1] if len(row) > 1 else "").split(",") if x],
                                      "done": {x for x in (row[2] if len(row) > 2 else "").split(",") if x}}
        log.info("Harada: загружено задач %s, дней привычек %s", len(self._task_row), len(self._habit_row))

    # ---------- задачи ----------
    def add_step(self, slot_id: str, delta: int = 1) -> int:
        t = core.slot(self.grid, slot_id)
        if not t or t["type"] != "task":
            raise KeyError(slot_id)
        with self.lock:
            cur = self.prog.task_done.get(slot_id, 0)
            new = max(0, min(t["steps"], cur + delta))
            self.prog.task_done[slot_id] = new
            if self.ss is not None and slot_id in self._task_row:
                r = self._task_row[slot_id]
                self.ws[TASKS_WS].update(range_name=f"D{r}:E{r}", values=[[new, dt.datetime.now().strftime("%Y-%m-%d %H:%M")]])
        return new

    # ---------- привычки ----------
    def toggle_habit(self, day: dt.date, code: str) -> bool:
        key = day.isoformat()
        with self.lock:
            s = set(self.prog.habit_log.get(key, set()))
            on = code not in s
            (s.add if on else s.discard)(code)
            self.prog.habit_log[key] = s
            if self.ss is not None:
                row = ["1" if c in s else "" for c in self._habit_header[1:]]
                ws = self.ws[HABITS_WS]
                if key in self._habit_row:
                    r = self._habit_row[key]
                    ws.update(range_name=f"A{r}", values=[[key] + row])
                else:
                    ws.append_row([key] + row)
                    self._habit_row[key] = len(ws.get_all_values())
        return on

    # ---------- фокус дня ----------
    def get_focus(self, day: dt.date) -> dict | None:
        return self.focus.get(day.isoformat())

    def set_focus(self, day: dt.date, ids: list[str], done: set[str] | None = None):
        key = day.isoformat()
        with self.lock:
            self.focus[key] = {"ids": list(ids), "done": set(done or set())}
            self._write_focus(key)

    def mark_focus_done(self, day: dt.date, slot_id: str):
        key = day.isoformat()
        with self.lock:
            f = self.focus.setdefault(key, {"ids": [], "done": set()})
            f["done"].add(slot_id)
            self._write_focus(key)

    def _write_focus(self, key: str):
        if self.ss is None:
            return
        f = self.focus[key]
        row = [key, ",".join(f["ids"]), ",".join(sorted(f["done"]))]
        ws = self.ws[FOCUS_WS]
        if key in self._focus_row:
            r = self._focus_row[key]
            ws.update(range_name=f"A{r}:C{r}", values=[row])
        else:
            ws.append_row(row)
            self._focus_row[key] = len(ws.get_all_values())
