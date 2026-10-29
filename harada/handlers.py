"""Telegram-часть сетки Харады: команды, кнопки и расписание."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

import pytz
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           InputMediaPhoto, Message)
from apscheduler.triggers.cron import CronTrigger

from . import core, render
from .store import HaradaStore

log = logging.getLogger(__name__)

HELP = (
    "🟧 *Сетка 9×9*\n"
    "/today — фокус дня: 3 задачи из сетки + привычки\n"
    "/check — отметить привычки за сегодня\n"
    "/step — закрыть шаг любой задачи\n"
    "/grid — вся сетка картинкой\n"
    "/habits — трекер привычек за месяц\n"
    "/progress — прогресс по блокам и чек-поинты"
)


class Harada:
    def __init__(self, store: HaradaStore, chat_id: int, tz: str):
        self.store = store
        self.grid = store.grid
        self.chat_id = chat_id
        self.tz = pytz.timezone(tz)
        self.router = Router(name="harada")
        self._routes()

    # ---------- общее ----------
    def today(self) -> dt.date:
        return dt.datetime.now(self.tz).date()

    def _mine(self, chat_id: int) -> bool:
        return chat_id == self.chat_id

    @staticmethod
    def _photo(png: bytes, name: str) -> BufferedInputFile:
        return BufferedInputFile(png, filename=name)

    def period(self, day: dt.date) -> tuple[dt.date, dt.date]:
        """Месяц трекера: с 28-го по 27-е (как в бумажной версии и чек-поинтах)."""
        if day.day >= 28:
            start = day.replace(day=28)
        else:
            prev = day.replace(day=1) - dt.timedelta(days=1)
            start = prev.replace(day=28)
        nxt = (start.replace(day=1) + dt.timedelta(days=32)).replace(day=27)
        start = max(start, core.d(self.grid["goal"]["start"]))
        return start, nxt

    # ---------- фокус дня ----------
    def ensure_focus(self, day: dt.date, reroll: bool = False) -> list[dict]:
        f = self.store.get_focus(day)
        if f and f["ids"] and not reroll:
            return [core.slot(self.grid, i) for i in f["ids"] if core.slot(self.grid, i)]
        done = set(f["done"]) if f else set()
        keep = [i for i in (f["ids"] if f else []) if i in done]          # сделанное сегодня остаётся на карточке
        skip = set(f["ids"]) | done if (f and reroll) else done
        new = core.focus_tasks(self.grid, self.store.prog, 3 - len(keep), skip=skip)
        if not new and reroll:                                              # других задач не осталось
            new = core.focus_tasks(self.grid, self.store.prog, 3 - len(keep), skip=done)
        ids = keep + [t["id"] for t in new]
        self.store.set_focus(day, ids, done)
        return [core.slot(self.grid, i) for i in ids]

    def today_kb(self, day: dt.date, focus: list[dict]) -> InlineKeyboardMarkup:
        done = (self.store.get_focus(day) or {}).get("done", set())
        row = [InlineKeyboardButton(text=("✔︎ " if t["id"] in done else "✅ ") + str(i + 1),
                                    callback_data=f"fd:{t['id']}") for i, t in enumerate(focus)]
        return InlineKeyboardMarkup(inline_keyboard=[
            row,
            [InlineKeyboardButton(text="☑️ Привычки", callback_data="hc:t"),
             InlineKeyboardButton(text="🔁 Другие задачи", callback_data="fr")],
        ])

    async def today_png(self, day: dt.date, focus: list[dict]) -> bytes:
        done = (self.store.get_focus(day) or {}).get("done", set())
        return await asyncio.to_thread(render.render_today, self.grid, self.store.prog, day, focus, set(done))

    async def send_today(self, bot: Bot, chat_id: int):
        day = self.today()
        focus = await asyncio.to_thread(self.ensure_focus, day)
        png = await self.today_png(day, focus)
        caption = "Нажми ✅ под номером, когда сделал шаг задачи."
        await bot.send_photo(chat_id, self._photo(png, "today.png"), caption=caption, reply_markup=self.today_kb(day, focus))

    # ---------- привычки ----------
    def check_kb(self, day: dt.date) -> InlineKeyboardMarkup:
        on = self.store.prog.habits_on(day)
        rows = []
        for h in core.habits_for_day(self.grid, day):
            mark = "✅" if h["code"] in on else "⬜"
            label = h["text"] if len(h["text"]) <= 34 else h["text"][:33] + "…"
            rows.append([InlineKeyboardButton(text=f"{mark} {h['code']} · {label}", callback_data=f"hb:{day.isoformat()}:{h['code']}")])
        today = self.today()
        other = today - dt.timedelta(days=1) if day == today else today
        rows.append([
            InlineKeyboardButton(text="◀ Вчера" if day == today else "Сегодня ▶", callback_data=f"hd:{other.isoformat()}"),
            InlineKeyboardButton(text="📊 Трекер", callback_data="hm"),
            InlineKeyboardButton(text="Готово", callback_data=f"hx:{day.isoformat()}"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def check_text(self, day: dt.date) -> str:
        hs = core.habits_for_day(self.grid, day)
        n = sum(1 for h in hs if h["code"] in self.store.prog.habits_on(day))
        label = "сегодня" if day == self.today() else day.strftime("%d.%m")
        return f"☑️ Привычки за {label}: {n} из {len(hs)}\nНажимай, чтобы отметить или снять отметку."

    async def send_check(self, bot: Bot, chat_id: int, day: dt.date | None = None):
        day = day or self.today()
        await bot.send_message(chat_id, self.check_text(day), reply_markup=self.check_kb(day))

    async def send_habits(self, bot: Bot, chat_id: int, day: dt.date | None = None):
        day = day or self.today()
        start, end = self.period(day)
        png = await asyncio.to_thread(render.render_habits, self.grid, self.store.prog, start, end, day)
        await bot.send_document(chat_id, self._photo(png, f"habits_{start:%Y%m%d}.png"),
                                caption=f"Трекер привычек · {start:%d.%m} – {end:%d.%m.%Y}")

    # ---------- шаги задач ----------
    def pillars_kb(self) -> InlineKeyboardMarkup:
        rows, row = [], []
        for p in self.grid["pillars"]:
            pct = core.pct(core.pillar_progress(self.grid, self.store.prog, p["id"]))
            row.append(InlineKeyboardButton(text=f"0{p['id']} {p['name'].title()} · {pct}", callback_data=f"sp:{p['id']}"))
            if len(row) == 2:
                rows.append(row); row = []
        if row:
            rows.append(row)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def tasks_kb(self, pid: int) -> InlineKeyboardMarkup:
        rows = []
        for t in core.tasks(self.grid):
            if t["pillar"] != pid:
                continue
            done = core.task_steps_done(self.store.prog, t)
            mark = "✅" if done >= t["steps"] else ("★" if t["star"] else "▫️")
            label = t["text"] if len(t["text"]) <= 30 else t["text"][:29] + "…"
            rows.append([InlineKeyboardButton(text=f"{mark} {label} · {done}/{t['steps']}", callback_data=f"st:{t['id']}"),
                         InlineKeyboardButton(text="↩", callback_data=f"su:{t['id']}")])
        rows.append([InlineKeyboardButton(text="◀ Блоки", callback_data="sb")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def pillar_text(self, pid: int) -> str:
        p = self.grid["pillars"][pid - 1]
        pct = core.pct(core.pillar_progress(self.grid, self.store.prog, pid))
        return f"0{pid} {p['name']} · {pct}\nНажми на задачу, чтобы засчитать шаг. ↩ — отменить шаг."

    # ---------- итоги ----------
    async def send_progress(self, bot: Bot, chat_id: int, title: str = "ПРОГРЕСС", extra: dict | None = None):
        png = await asyncio.to_thread(render.render_progress, self.grid, self.store.prog, self.today(), title, extra)
        await bot.send_photo(chat_id, self._photo(png, "progress.png"))

    async def send_grid(self, bot: Bot, chat_id: int):
        png = await asyncio.to_thread(render.render_grid, self.grid, self.store.prog, self.today())
        closed, total = core.tasks_closed(self.grid, self.store.prog)
        await bot.send_document(chat_id, self._photo(png, "grid_9x9.png"), caption=f"Сетка 9×9 · закрыто {closed} из {total} задач")

    async def evening_job(self, bot: Bot):
        await self.send_check(bot, self.chat_id)

    async def summary_job(self, bot: Bot):
        """27-го каждого месяца: итог месяца. В даты чек-поинтов — карточка чек-поинта."""
        day = self.today()
        cps = core.checkpoints(self.grid)
        is_cp = day in cps
        if day.day != 27 and not is_cp:
            return
        start, end = self.period(day)
        if is_cp:
            start = core.period_start(self.grid, cps.index(day) + 1)
        rate = core.habits_rate(self.grid, self.store.prog, start, day)
        closed, total = core.tasks_closed(self.grid, self.store.prog)
        await self.send_habits(bot, self.chat_id, day)
        if is_cp:
            i = cps.index(day) + 1
            final = i == len(cps)
            title = "ФИНАЛ" if final else f"ЧЕК-ПОИНТ {i}"
            await self.send_progress(bot, self.chat_id, title, {"ПРИВЫЧКИ ЗА ЭТАП": core.pct(rate), "ЗАДАЧ ЗАКРЫТО": f"{closed}/{total}"})
            lines = [f"🟧 *{title.title()}* · {day:%d.%m.%Y}",
                     f"Привычки за этап: {core.pct(rate)}", f"Задач закрыто: {closed} из {total}", ""]
            if final:
                lines += ["Цель достигнута, если:"] + [f"• {m}" for m in self.grid["goal"]["markers"]]
            else:
                lines += ["Что сделать сегодня:", "1. Что убираю из сетки, что добавляю",
                          "2. Выбрать новые ★ на следующий этап", "3. Записать цифры на стр. 2 бумажной версии"]
            await bot.send_message(self.chat_id, "\n".join(lines), parse_mode="Markdown")
        else:
            await bot.send_message(self.chat_id, f"🟧 Итог месяца · привычки {core.pct(rate)} · задач закрыто {closed} из {total}")

    def schedule(self, scheduler, bot: Bot, evening: str = "21:00"):
        """Вечерний чек-ин привычек в evening, итог месяца / чек-поинт через 15 минут после него."""
        hh, mm = (int(x) for x in evening.split(":"))
        later = dt.datetime(2000, 1, 1, hh, mm) + dt.timedelta(minutes=15)
        scheduler.add_job(self.evening_job, CronTrigger(hour=hh, minute=mm, timezone=self.tz), args=[bot], id="harada_evening")
        scheduler.add_job(self.summary_job, CronTrigger(hour=later.hour, minute=later.minute, timezone=self.tz),
                          args=[bot], id="harada_summary")

    # ---------- маршруты ----------
    def _routes(self):
        r = self.router
        own = F.chat.id == self.chat_id
        own_cb = F.message.chat.id == self.chat_id

        @r.message(Command("today"), own)
        async def _today(m: Message, bot: Bot):
            await self.send_today(bot, m.chat.id)

        @r.message(Command("check"), own)
        async def _check(m: Message, bot: Bot):
            await self.send_check(bot, m.chat.id)

        @r.message(Command("grid"), own)
        async def _grid(m: Message, bot: Bot):
            await self.send_grid(bot, m.chat.id)

        @r.message(Command("habits"), own)
        async def _habits(m: Message, bot: Bot):
            await self.send_habits(bot, m.chat.id)

        @r.message(Command("progress"), own)
        async def _progress(m: Message, bot: Bot):
            await self.send_progress(bot, m.chat.id)

        @r.message(Command("step"), own)
        async def _step(m: Message):
            await m.answer("Выбери блок:", reply_markup=self.pillars_kb())

        @r.message(Command("grid_help"), own)
        async def _help(m: Message):
            await m.answer(HELP, parse_mode="Markdown")

        # Команды сетки из чужого чата: подсказываем, какой CHAT_ID поставить, вместо молчания
        @r.message(Command("today", "check", "grid", "habits", "progress", "step", "grid_help"))
        async def _wrong_chat(m: Message):
            log.warning("Harada: команда из чата %s, а CHAT_ID=%s", m.chat.id, self.chat_id)
            await m.answer(  # без Markdown: «_» в CHAT_ID ломает разметку
                "Сетка привязана к другому чату.\n"
                f"Твой chat id: {m.chat.id}\n\n"
                "Поставь свой id в Railway → Variables → CHAT_ID, бот перезапустится сам."
            )

        # --- кнопки: фокус дня ---
        @r.callback_query(F.data.startswith("fd:"), own_cb)
        async def _focus_done(c: CallbackQuery):
            sid = c.data[3:]
            day = self.today()
            f = self.store.get_focus(day) or {"done": set()}
            if sid in f["done"]:
                await c.answer("Уже засчитано сегодня")
                return
            t = core.slot(self.grid, sid)
            new = await asyncio.to_thread(self.store.add_step, sid, 1)
            await asyncio.to_thread(self.store.mark_focus_done, day, sid)
            focus = self.ensure_focus(day)
            png = await self.today_png(day, focus)
            await c.message.edit_media(InputMediaPhoto(media=self._photo(png, "today.png"), caption=c.message.caption),
                                       reply_markup=self.today_kb(day, focus))
            msg = "Задача закрыта! 🔥" if new >= t["steps"] else f"Шаг засчитан: {new}/{t['steps']}"
            await c.answer(msg)

        @r.callback_query(F.data == "fr", own_cb)
        async def _focus_reroll(c: CallbackQuery):
            day = self.today()
            focus = await asyncio.to_thread(self.ensure_focus, day, True)
            png = await self.today_png(day, focus)
            await c.message.edit_media(InputMediaPhoto(media=self._photo(png, "today.png"), caption=c.message.caption),
                                       reply_markup=self.today_kb(day, focus))
            await c.answer("Подобрал другие задачи")

        # --- кнопки: привычки ---
        @r.callback_query(F.data == "hc:t", own_cb)
        async def _open_check(c: CallbackQuery, bot: Bot):
            await self.send_check(bot, c.message.chat.id)
            await c.answer()

        @r.callback_query(F.data.startswith("hb:"), own_cb)
        async def _toggle(c: CallbackQuery):
            _, ds, code = c.data.split(":")
            day = dt.date.fromisoformat(ds)
            on = await asyncio.to_thread(self.store.toggle_habit, day, code)
            await c.message.edit_text(self.check_text(day), reply_markup=self.check_kb(day))
            await c.answer(f"{code} {'✅' if on else 'снято'}")

        @r.callback_query(F.data.startswith("hd:"), own_cb)
        async def _switch_day(c: CallbackQuery):
            day = dt.date.fromisoformat(c.data[3:])
            await c.message.edit_text(self.check_text(day), reply_markup=self.check_kb(day))
            await c.answer()

        @r.callback_query(F.data == "hm", own_cb)
        async def _tracker(c: CallbackQuery, bot: Bot):
            await c.answer("Рисую трекер…")
            await self.send_habits(bot, c.message.chat.id)

        @r.callback_query(F.data.startswith("hx:"), own_cb)
        async def _check_done(c: CallbackQuery):
            day = dt.date.fromisoformat(c.data[3:])
            hs = core.habits_for_day(self.grid, day)
            n = sum(1 for h in hs if h["code"] in self.store.prog.habits_on(day))
            start, _ = self.period(day)
            rate = core.habits_rate(self.grid, self.store.prog, start, day)
            await c.message.edit_text(f"✅ Сохранено: {n} из {len(hs)} за {day:%d.%m}\nЗа месяц трекера: {core.pct(rate)}")
            await c.answer()

        # --- кнопки: шаги задач ---
        @r.callback_query(F.data.startswith("sp:"), own_cb)
        async def _pillar(c: CallbackQuery):
            pid = int(c.data[3:])
            await c.message.edit_text(self.pillar_text(pid), reply_markup=self.tasks_kb(pid))
            await c.answer()

        @r.callback_query(F.data == "sb", own_cb)
        async def _back(c: CallbackQuery):
            await c.message.edit_text("Выбери блок:", reply_markup=self.pillars_kb())
            await c.answer()

        @r.callback_query(F.data.startswith(("st:", "su:")), own_cb)
        async def _task_step(c: CallbackQuery):
            sid, delta = c.data[3:], (1 if c.data.startswith("st:") else -1)
            t = core.slot(self.grid, sid)
            before = core.task_steps_done(self.store.prog, t)
            new = await asyncio.to_thread(self.store.add_step, sid, delta)
            if new == before:
                await c.answer("Уже закрыто" if delta > 0 else "Нечего отменять")
                return
            await c.message.edit_text(self.pillar_text(t["pillar"]), reply_markup=self.tasks_kb(t["pillar"]))
            await c.answer("Задача закрыта! 🔥" if new >= t["steps"] else f"{new}/{t['steps']}")
