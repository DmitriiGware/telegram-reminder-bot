import asyncio
import logging
import os
from dotenv import load_dotenv


from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import CallbackQuery
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")



#adding a button menu
def main_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить напоминание | Add a notice", callback_data="add")],
            [InlineKeyboardButton(text="Мои напоминания | My Notice", callback_data="list")],
            [InlineKeyboardButton(text="Удалить напоминание | Delete", callback_data="delete")],
            [InlineKeyboardButton(text="Помощь", callback_data="help")]
        ]

    )
    return keyboard

def cancel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена | Cancel", callback_data="cancel_add")]
        ]
    )


def parse_time_hhmm(s: str):

    s = (s or "").strip()
    if not s:
        return None

    s = s.replace(".", ":")
    s = s.replace(" ", "")

    if ":" not in s:
        return None

    parts = s.split(":")
    if len(parts) != 2:
        return None

    hh, mm = parts[0].strip(), parts[1].strip()

    if not (hh.isdigit() and mm.isdigit()):
        return None

    h, m = int(hh), int(mm)

    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None

    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return datetime(2000, 1, 1, hour=h, minute=m)

def parse_date_ddmmyyyy(s: str):
    """
    Принимает:
    - "17.02.2026"
    - "17/02/2026"
    - "today" / "сегодня"
    - "tomorrow" / "завтра"
    Возвращает date (без времени) или None.
    """
    s = (s or "").strip().lower()
    if not s:
        return None

    now = datetime.now()

    if s in ("today", "сегодня"):
        return now.date()
    if s in ("tomorrow", "завтра"):
        return (now + timedelta(days=1)).date()

    s = s.replace("/", ".")
    parts = s.split(".")
    if len(parts) != 3:
        return None

    dd, mm, yyyy = parts
    if not (dd.isdigit() and mm.isdigit() and yyyy.isdigit()):
        return None

    d, m, y = int(dd), int(mm), int(yyyy)

    try:
        return datetime(year=y, month=m, day=d).date()
    except ValueError:
        return None

# --- STORAGE IN MEMORY ---
REMINDERS = {}
NEXT_ID = {}

async def scheduler_loop(bot: Bot):
    while True:
        now = datetime.now()

        for user_id, items in list(REMINDERS.items()):
            if not items:
                continue

            due = [r for r in items if r["when"] <= now]
            if not due:
                continue

            for r in due:
                try:
                    await bot.send_message(
                        r["chat_id"],
                        f"⏰ Напоминание #{r['id']}\n{r['text']}\n\n({r['when'].strftime('%d.%m.%Y %H:%M')})"
                    )
                except Exception as e:
                    logging.warning(f"Send failed: {e}")

            # оставляем только будущие
            REMINDERS[user_id] = [r for r in items if r["when"] > now]

        await asyncio.sleep(1)

#main structure
async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    asyncio.create_task(scheduler_loop(bot))

    class AddReminder(StatesGroup):
        waiting_text = State()
        waiting_date = State()
        waiting_time = State()
        waiting_delete_id = State()


    @dp.callback_query()
    async def callbacks(call: CallbackQuery, state: FSMContext):
        if call.data == "add":
            await state.set_state(AddReminder.waiting_text)
            await call.message.answer("Напиши текст напоминания.",reply_markup=cancel_kb())

        elif call.data == "delete":
            user_id = call.from_user.id
            items = REMINDERS.get(user_id, [])
            if not items:
                await call.message.answer("Удалять нечего - напоминаний нет.", reply_markup=main_menu())
            else:
                await state.set_state(AddReminder.waiting_delete_id)
                await call.message.answer(
                    "Введи номер напоминания (id), которое удалить.\n"
                    "Подсказка: нажми 'Мои напоминания' и посмотри номер (#).",
                    reply_markup=cancel_kb()
                )

        elif call.data == "list":
            user_id = call.from_user.id
            items = REMINDERS.get(user_id, [])

            if not items:
                await call.message.answer("Пока напоминаний нет.", reply_markup=main_menu())
            else:
                lines = ["📌 Твои напоминания:"]
                for r in items:
                    lines.append(f"#{r['id']} — {r['when'].strftime('%d.%m.%Y %H:%M')} — {r['text']}")
                await call.message.answer("\n".join(lines), reply_markup=main_menu())
        elif call.data == "cancel_add":
            await state.clear()
            await call.message.answer("Отменено.", reply_markup=main_menu())
        elif call.data == "help":
            await call.message.answer(
                "_________________________Помощь_________________________ \n\n"
                "Этот бот будет присылать напоминания в нужное время."
            )
        await call.answer()


#Handlers


    @dp.message(AddReminder.waiting_text)
    async def get_reminder_text(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправь обычный текст")
            return

        await state.update_data(text=text)
        await state.set_state(AddReminder.waiting_date)
        await message.answer(
            "📅 Теперь введи дату в формате DD.MM.YYYY (например 17.02.2026)\n"
            "Можно написать: сегодня / завтра",
            reply_markup=cancel_kb()
        )

    @dp.message(AddReminder.waiting_date)
    async def get_reminder_date(message: Message, state: FSMContext):
        date_str = (message.text or "").strip()
        d = parse_date_ddmmyyyy(date_str)
        if d is None:
            await message.answer(
                "Не понял дату 😅\n"
                "Введи так: DD.MM.YYYY (например 17.02.2026)\n"
                "Или напиши: сегодня / завтра",
                reply_markup=cancel_kb()
            )
            return

        await state.update_data(date=d.isoformat())
        await state.set_state(AddReminder.waiting_time)
        await message.answer(
            "⏰ Теперь введи время: 9.30 / 09:30 / 9:30",
            reply_markup=cancel_kb()
        )

    @dp.message(AddReminder.waiting_time)
    async def get_reminder_time(message: Message, state: FSMContext):
        time_str = (message.text or "").strip()
        t = parse_time_hhmm(time_str)
        if t is None:
            await message.answer("Не понял время. Пример: 9.30 / 09:30 / 9:30", reply_markup=cancel_kb())
            return

        data = await state.get_data()
        text = (data.get("text") or "").strip()
        date_iso = data.get("date")  # "YYYY-MM-DD"

        if not text or not date_iso:
            await state.clear()
            await message.answer("Данные потерялись. Нажми «Добавить» заново.", reply_markup=main_menu())
            return

        # собираем target = выбранная дата + выбранное время
        chosen_date = datetime.fromisoformat(date_iso).date()

        now = datetime.now()
        target = datetime(
            year=chosen_date.year,
            month=chosen_date.month,
            day=chosen_date.day,
            hour=t.hour,
            minute=t.minute,
            second=0,
            microsecond=0,
        )

        # если дата=сегодня и время уже прошло — предупредим и не будем автоматически переносить
        if target <= now:
            await message.answer(
                "⚠️ Это время уже прошло.\n"
                "Выбери другое время или дату (например завтра).",
                reply_markup=cancel_kb()
            )
            return

        data = await state.get_data()
        text = (data.get("text") or "").strip()
        user_id = message.from_user.id
        chat_id = message.chat.id

        if user_id not in REMINDERS:
            REMINDERS[user_id] = []
        if user_id not in NEXT_ID:
            NEXT_ID[user_id] = 1

        rid = NEXT_ID[user_id]
        NEXT_ID[user_id] += 1

        REMINDERS[user_id].append({
            "id": rid,
            "chat_id": chat_id,
            "text": text,
            "when": target,
        })
        if not text:
            await state.clear()
            await message.answer("Текст напоминалки затерялся. Давай заново: нажми 'Добавить'")
            return

        await state.clear()
        await message.answer(
            f"✅ Готово!\n"
            f"Напоминание #{rid}\n"
            f"Текст: {text}\n"
            f"Время: {target.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=main_menu()
        )

    @dp.message(AddReminder.waiting_delete_id)
    async def delete_by_id(message: Message, state: FSMContext):
        user_id = message.from_user.id
        s = (message.text or "").strip()

        if not s.isdigit():
            await message.answer("Введи только число (например 1).", reply_markup=cancel_kb())
            return

        rid = int(s)
        items = REMINDERS.get(user_id, [])

        # ищем и удаляем
        before = len(items)
        items = [r for r in items if r["id"] != rid]
        after = len(items)

        REMINDERS[user_id] = items

        await state.clear()

        if after == before:
            await message.answer(f"Не нашёл напоминание с id #{rid}.", reply_markup=main_menu())
        else:
            await message.answer(f"✅ Удалил напоминание #{rid}.", reply_markup=main_menu())

    @dp.message(CommandStart())
    async def start(message: Message):
        await message.answer(
            "Привет! | Hello! \n"
            "Я бот_напоминалка. | This is Bot_reminder. \n\n"
            "Команды: | Commands: \n "
            "/start - старт | start\n"
            "/add - добавить напоминание | add a notice\n"
            "/list - показать напоминание | show list\n"
            "/help - помощь | help\n"
            "Выбери действие: | choose the option:",
            reply_markup=main_menu()
        )

    @dp.message(Command("help"))
    async def help_cmd(message: Message):
        await message.answer(
            "🆘 Помощь по боту-напоминалке\n\n"
            "📌 Как добавить напоминание:\n"
            "1️⃣ Нажми «Добавить напоминание»\n"
            "2️⃣ Введи текст\n"
            "3️⃣ Введи дату (например 17.02.2026)\n"
            "   Можно написать: сегодня / завтра\n"
            "4️⃣ Введи время: 9.30 / 09:30 / 9:30\n\n"
            "📋 «Мои напоминания» — показывает список активных напоминаний\n"
            "🗑 «Удалить напоминание» — введи номер (#), чтобы удалить\n"
            "❌ Кнопка «Отмена» — прерывает добавление\n\n"
            "⌚ Напоминание придёт точно в выбранные дату и время.\n\n"
            "Команды:\n"
            "/start — главное меню\n"
            "/help — эта справка"
        )

    await dp.start_polling(bot)



if __name__ == '__main__':
    asyncio.run(main())