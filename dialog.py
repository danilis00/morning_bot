import json
import os
from datetime import datetime


# Dialog states
IDLE = "idle"
S1_GOOD = "s1_good"
S1_BETTER = "s1_better"
S1_BLOCKED = "s1_blocked"
S2_IMPROVE = "s2_improve"
S3_CONFIRM = "s3_confirm"
S4_TASKS = "s4_tasks"
S4_GOAL_STEP = "s4_goal_step"
DONE = "done"

STEPS = {
    S1_GOOD: "📝 *Шаг 1 из 4 — Анализ вчерашнего дня*\n\nЧто вчера получилось хорошо?",
    S1_BETTER: "Что можно было сделать лучше?",
    S1_BLOCKED: "Что мешало двигаться вперёд?",
    S2_IMPROVE: "💡 *Шаг 2 из 4 — Одно улучшение*\n\nЧто одну вещь ты улучшишь сегодня? Конкретно и коротко.",
    S3_CONFIRM: (
        "⏱ *Шаг 3 из 4 — 30 минут на улучшение*\n\n"
        "Отлично! Сегодня посвяти 30 минут только этому улучшению.\n\n"
        "Когда сделаешь — напиши *готово* (или нажми /skip чтобы пропустить)."
    ),
    S4_TASKS: "📋 *Шаг 4 из 4 — План дня*\n\nЗапиши три главные задачи дня (через запятую или с новой строки).",
    S4_GOAL_STEP: "Один шаг, который сегодня приблизит тебя к главной цели?",
}

# Persistent state stored in a simple JSON file (works on Railway)
STATE_FILE = "/tmp/dialog_state.json"


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


class DialogManager:
    def __init__(self, db):
        self.db = db

    def _get(self) -> dict:
        return load_state()

    def _set(self, state: dict):
        save_state(state)

    async def start(self, bot, chat_id: int):
        greeting = (
            f"☀️ Доброе утро! Время утреннего ритуала.\n"
            f"Сегодня {datetime.now().strftime('%d %B %Y')}.\n\n"
        )
        await bot.send_message(chat_id, greeting + STEPS[S1_GOOD], parse_mode="Markdown")
        self._set({"step": S1_GOOD, "data": {}, "chat_id": chat_id})

    async def handle_answer(self, bot, chat_id: int, text: str):
        state = self._get()

        if not state or state.get("chat_id") != chat_id:
            await bot.send_message(
                chat_id,
                "Напиши /ritual чтобы начать утренний ритуал, или /history чтобы посмотреть историю."
            )
            return

        step = state.get("step", IDLE)
        data = state.get("data", {})

        if step == S1_GOOD:
            data["good"] = text
            state.update({"step": S1_BETTER, "data": data})
            self._set(state)
            await bot.send_message(chat_id, STEPS[S1_BETTER])

        elif step == S1_BETTER:
            data["better"] = text
            state.update({"step": S1_BLOCKED, "data": data})
            self._set(state)
            await bot.send_message(chat_id, STEPS[S1_BLOCKED])

        elif step == S1_BLOCKED:
            data["blocked"] = text
            state.update({"step": S2_IMPROVE, "data": data})
            self._set(state)
            await bot.send_message(chat_id, STEPS[S2_IMPROVE], parse_mode="Markdown")

        elif step == S2_IMPROVE:
            data["improve"] = text
            state.update({"step": S3_CONFIRM, "data": data})
            self._set(state)
            await bot.send_message(chat_id, STEPS[S3_CONFIRM], parse_mode="Markdown")

        elif step == S3_CONFIRM:
            if text.strip().lower() in ("готово", "done", "/skip"):
                state.update({"step": S4_TASKS, "data": data})
                self._set(state)
                await bot.send_message(chat_id, STEPS[S4_TASKS], parse_mode="Markdown")
            else:
                await bot.send_message(
                    chat_id,
                    "Как сделаешь — напиши *готово* 👊",
                    parse_mode="Markdown"
                )

        elif step == S4_TASKS:
            data["tasks"] = text
            state.update({"step": S4_GOAL_STEP, "data": data})
            self._set(state)
            await bot.send_message(chat_id, STEPS[S4_GOAL_STEP])

        elif step == S4_GOAL_STEP:
            data["goal_step"] = text
            state.update({"step": DONE, "data": data})
            self._set(state)

            # Save to Google Sheets
            self.db.save_entry(data)

            summary = (
                "✅ *Ритуал завершён!*\n\n"
                f"📌 Улучшение дня: _{data.get('improve', '—')}_\n"
                f"🎯 Шаг к цели: _{data.get('goal_step', '—')}_\n\n"
                "Отличный старт! Удачного дня 🚀\n\n"
                "Посмотреть историю: /history\nСтатистика: /stats"
            )
            await bot.send_message(chat_id, summary, parse_mode="Markdown")
