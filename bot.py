import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from sheets import SheetsDB
from dialog import DialogManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Moscow")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = SheetsDB()
dialog = DialogManager(db)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я твой утренний ритуал-бот 🌅\n\n"
        "Каждый день в 7:00 я буду задавать тебе вопросы по 4 шагам:\n"
        "1️⃣ Анализ вчерашнего дня\n"
        "2️⃣ Выбор одного улучшения\n"
        "3️⃣ Напоминание о 30-минутной работе над улучшением\n"
        "4️⃣ План на сегодня\n\n"
        "Или начни прямо сейчас командой /ritual"
    )


@dp.message(Command("ritual"))
async def cmd_ritual(message: Message):
    await dialog.start(bot, message.chat.id)


@dp.message(Command("history"))
async def cmd_history(message: Message):
    records = db.get_last_entries(7)
    if not records:
        await message.answer("Пока нет записей. Начни первый ритуал командой /ritual")
        return
    text = "📋 *Последние 7 дней:*\n\n"
    for r in records:
        text += f"📅 *{r['date']}*\n"
        text += f"✅ Хорошо: {r.get('good', '—')}\n"
        text += f"🔧 Улучшение: {r.get('improve', '—')}\n"
        text += f"🎯 Главные задачи: {r.get('tasks', '—')}\n\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    stats = db.get_stats()
    text = (
        f"📊 *Твоя статистика:*\n\n"
        f"🔥 Всего ритуалов: {stats['total']}\n"
        f"📅 Дней подряд: {stats['streak']}\n"
        f"🗓 Первый ритуал: {stats['first_date']}\n"
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(F.text)
async def handle_text(message: Message):
    await dialog.handle_answer(bot, message.chat.id, message.text)


async def scheduled_ritual():
    logger.info("Starting scheduled morning ritual")
    await dialog.start(bot, CHAT_ID)


async def main():
    scheduler = AsyncIOScheduler(timezone=pytz.timezone(TIMEZONE))
    scheduler.add_job(
        scheduled_ritual,
        CronTrigger(hour=7, minute=0, timezone=TIMEZONE),
    )
    scheduler.start()
    logger.info(f"Scheduler started. Ritual runs at 7:00 {TIMEZONE}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
