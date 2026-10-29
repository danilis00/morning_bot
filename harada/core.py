"""Сетка Харады: данные и расчёты, без привязки к Telegram и хранилищу."""
from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

GRID_PATH = Path(__file__).with_name("grid.json")

WEEKLY_QUOTA = {"1×/нед": 1, "2×/нед": 2, "3×/нед": 3}


def load_grid(path: Path | str = GRID_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


@dataclass
class Progress:
    """Состояние пользователя. task_done: id слота -> сколько шагов закрыто.
    habit_log: 'YYYY-MM-DD' -> множество кодов привычек (R1…), отмеченных в этот день."""
    task_done: dict[str, int] = field(default_factory=dict)
    habit_log: dict[str, set[str]] = field(default_factory=dict)

    def habits_on(self, day: dt.date) -> set[str]:
        return self.habit_log.get(day.isoformat(), set())


# ---------- справочники ----------

def tasks(grid: dict) -> list[dict]:
    return [s | {"pillar": p["id"]} for p in grid["pillars"] for s in p["slots"] if s["type"] == "task"]


def habits(grid: dict) -> list[dict]:
    hs = [s | {"pillar": p["id"]} for p in grid["pillars"] for s in p["slots"] if s["type"] == "habit"]
    return sorted(hs, key=lambda h: int(h["code"][1:]))


def slot(grid: dict, slot_id: str) -> dict | None:
    for p in grid["pillars"]:
        for s in p["slots"]:
            if s["id"] == slot_id:
                return s | {"pillar": p["id"]}
    return None


# ---------- привычки ----------

def habit_scheduled(h: dict, day: dt.date) -> bool:
    """Нужно ли делать привычку в этот день (для «Пн–Пт» и «Вс»). Квотные (N×/нед) — каждый день допустим."""
    if h["freq"] == "Пн–Пт":
        return day.weekday() < 5
    if h["freq"] == "Вс":
        return day.weekday() == 6
    return True


def habits_for_day(grid: dict, day: dt.date) -> list[dict]:
    return [h for h in habits(grid) if habit_scheduled(h, day)]


def habit_rate(grid: dict, prog: Progress, code: str, start: dt.date, end: dt.date) -> float | None:
    """Доля выполнения привычки за период [start, end]. Для N×/нед считаем по неделям: min(сделано, N) / N."""
    h = next(x for x in habits(grid) if x["code"] == code)
    if end < start:
        return None
    days = [start + dt.timedelta(i) for i in range((end - start).days + 1)]
    if h["freq"] in WEEKLY_QUOTA:
        quota = WEEKLY_QUOTA[h["freq"]]
        weeks: dict[tuple, int] = {}
        for day in days:
            key = day.isocalendar()[:2]
            weeks.setdefault(key, 0)
            if code in prog.habits_on(day):
                weeks[key] += 1
        if not weeks:
            return None
        return sum(min(v, quota) for v in weeks.values()) / (quota * len(weeks))
    due = [x for x in days if habit_scheduled(h, x)]
    if not due:
        return None
    return sum(1 for x in due if code in prog.habits_on(x)) / len(due)


def habits_rate(grid: dict, prog: Progress, start: dt.date, end: dt.date) -> float | None:
    rates = [r for h in habits(grid) if (r := habit_rate(grid, prog, h["code"], start, end)) is not None]
    return sum(rates) / len(rates) if rates else None


def streak(grid: dict, prog: Progress, code: str, today: dt.date) -> int:
    """Сколько запланированных дней подряд привычка выполнена (сегодня не обнуляет, если ещё не отмечено)."""
    h = next(x for x in habits(grid) if x["code"] == code)
    n, day = 0, today
    if code not in prog.habits_on(day):
        day -= dt.timedelta(1)
    for _ in range(400):
        if habit_scheduled(h, day) and h["freq"] not in WEEKLY_QUOTA:
            if code in prog.habits_on(day):
                n += 1
            else:
                break
        elif h["freq"] in WEEKLY_QUOTA:
            if code in prog.habits_on(day):
                n += 1
            elif (today - day).days > 7:
                break
        day -= dt.timedelta(1)
    return n


# ---------- задачи ----------

def task_steps_done(prog: Progress, t: dict) -> int:
    return max(0, min(t["steps"], prog.task_done.get(t["id"], 0)))


def task_closed(prog: Progress, t: dict) -> bool:
    return task_steps_done(prog, t) >= t["steps"]


def tasks_closed(grid: dict, prog: Progress) -> tuple[int, int]:
    ts = tasks(grid)
    return sum(task_closed(prog, t) for t in ts), len(ts)


def pillar_progress(grid: dict, prog: Progress, pillar_id: int) -> float:
    """Доля закрытых шагов задач в блоке (привычки не входят)."""
    ts = [t for t in tasks(grid) if t["pillar"] == pillar_id]
    total = sum(t["steps"] for t in ts)
    return sum(task_steps_done(prog, t) for t in ts) / total if total else 0.0


def focus_tasks(grid: dict, prog: Progress, n: int = 3, skip: set[str] | None = None) -> list[dict]:
    """Задачи для утреннего фокуса: сначала незакрытые ★, потом остальные; не больше одной на блок, пока есть выбор."""
    skip = skip or set()
    open_ = [t for t in tasks(grid) if not task_closed(prog, t) and t["id"] not in skip]
    open_.sort(key=lambda t: (not t["star"], t["pillar"], t["id"]))
    picked, used = [], set()
    for t in open_:
        if t["pillar"] not in used:
            picked.append(t); used.add(t["pillar"])
        if len(picked) == n:
            return picked
    for t in open_:
        if t not in picked:
            picked.append(t)
        if len(picked) == n:
            break
    return picked


# ---------- чек-поинты ----------

def checkpoints(grid: dict) -> list[dt.date]:
    return [d(x) for x in grid["goal"]["checkpoints"]]


def next_checkpoint(grid: dict, today: dt.date) -> tuple[int, dt.date] | None:
    for i, c in enumerate(checkpoints(grid)):
        if c >= today:
            return i + 1, c
    return None


def period_start(grid: dict, cp_index: int) -> dt.date:
    """Начало периода для чек-поинта №cp_index (1-based)."""
    cps = checkpoints(grid)
    return d(grid["goal"]["start"]) if cp_index == 1 else cps[cp_index - 2] + dt.timedelta(1)


def pct(x: float | None) -> str:
    return "—" if x is None else f"{math.floor(x * 100 + 0.5)}%"
