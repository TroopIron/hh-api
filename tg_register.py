# tg_register.py
import os
import logging
from dotenv import load_dotenv

import aiosqlite
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, types

from settings_utils import (
    save_user_setting,
    get_user_setting,
    build_settings_keyboard,
    set_pending,
    get_pending,
)
from resume_utils import build_resume_keyboard
import hh_api

# ────────────────────────────
# Базовая инициализация
# ────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("TG_BOT_TOKEN not set in .env or environment")
    raise RuntimeError("TG_BOT_TOKEN not set")

bot = Bot(token=BOT_TOKEN)
app = FastAPI()

DB_PATH = "tg_users.db"

# ────────────────────────────
# Константы-подсказки для фильтров
# ────────────────────────────
SCHEDULE_SUGGESTIONS = [
    "полный день",
    "гибкий график",
    "сменный график",
]

WORK_FORMAT_SUGGESTIONS = [
    "дистанционно",
    "офис",
    "гибрид",
]

EMPLOYMENT_TYPE_SUGGESTIONS = [
    "полная",
    "частичная",
    "проектная",
    "стажировка",
]

SALARY_SUGGESTIONS = ["50000", "100000", "150000"]

# ────────────────────────────
# FastAPI-хуки
# ────────────────────────────
@app.on_event("startup")
async def on_startup():
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(webhook_url)
        logger.info(f"Webhook installed: {webhook_url}")


@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()

# ────────────────────────────
# Основной вебхук Telegram
# ────────────────────────────
@app.post("/bot{token:path}")
async def telegram_webhook(request: Request, token: str):
    # Валидация токена вебхука
    if token != BOT_TOKEN:
        logger.warning("Invalid webhook token: %s", token)
        raise HTTPException(status_code=403, detail="Invalid token")

    body = await request.json()
    update = types.Update(**body)

    # ────────── Callback-кнопки ──────────
    if update.callback_query:
        call = update.callback_query
        user_id = call.from_user.id

        # гарантируем наличие пользователя в БД
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users(chat_id) VALUES (?)",
                (user_id,),
            )
            await db.commit()

        data = call.data

        # 1. запуск ввода по фильтрам
        if data == "filter_region":
            await set_pending(user_id, "region")
            await bot.send_message(user_id, "Введите название региона:")
        elif data == "filter_schedule":
            await set_pending(user_id, "schedule")
            await bot.send_message(
                user_id, "Введите желаемый график (например, полный день):"
            )
        elif data == "filter_work_format":
            await set_pending(user_id, "work_format")
            await bot.send_message(
                user_id, "Введите формат работы (дистанционно/офис/гибрид):"
            )
        elif data == "filter_salary":
            await set_pending(user_id, "salary")
            await bot.send_message(user_id, "Введите минимальную зарплату в рублях:")
        elif data == "filter_employment_type":
            await set_pending(user_id, "employment_type")
            await bot.send_message(
                user_id, "Введите тип занятости (полная/частичная/проектная):"
            )
        elif data == "filter_keyword":
            await set_pending(user_id, "keyword")
            await bot.send_message(user_id, "Введите ключевое слово для поиска:")

        # 2. выбор значения из подсказок
        elif data.startswith("region_suggest_"):
            area_id = int(data.split("_")[-1])
            await save_user_setting(user_id, "region", area_id)
            await set_pending(user_id, None)

            await bot(call.answer())
            await bot(call.message.edit_reply_markup())

            await bot.send_message(user_id, "✅ Регион установлен!")
            await bot.send_message(
                user_id, "Ваши настройки:", reply_markup=build_settings_keyboard()
            )

        elif data.startswith("schedule_suggest_"):
            value = data.split("_")[-1]
            await save_user_setting(user_id, "schedule", value)
            await set_pending(user_id, None)

            await bot(call.answer())
            await bot(call.message.edit_reply_markup())

            await bot.send_message(user_id, "✅ График работы установлен!")
            await bot.send_message(
                user_id, "Ваши настройки:", reply_markup=build_settings_keyboard()
            )

        elif data.startswith("work_format_suggest_"):
            value = data.split("_")[-1]
            await save_user_setting(user_id, "work_format", value)
            await set_pending(user_id, None)

            await bot(call.answer())
            await bot(call.message.edit_reply_markup())

            await bot.send_message(user_id, "✅ Формат работы установлен!")
            await bot.send_message(
                user_id, "Ваши настройки:", reply_markup=build_settings_keyboard()
            )

        elif data.startswith("salary_suggest_"):
            value = data.split("_")[-1]
            await save_user_setting(user_id, "salary", value)
            await set_pending(user_id, None)

            await bot(call.answer())
            await bot(call.message.edit_reply_markup())

            await bot.send_message(user_id, "✅ Зарплата установлена!")
            await bot.send_message(
                user_id, "Ваши настройки:", reply_markup=build_settings_keyboard()
            )

        elif data.startswith("employment_type_suggest_"):
            value = data.split("_")[-1]
            await save_user_setting(user_id, "employment_type", value)
            await set_pending(user_id, None)

            await bot(call.answer())
            await bot(call.message.edit_reply_markup())

            await bot.send_message(user_id, "✅ Тип занятости установлен!")
            await bot.send_message(
                user_id, "Ваши настройки:", reply_markup=build_settings_keyboard()
            )

        # 3. выбор резюме
        elif data.startswith("select_resume_"):
            resume_id = data.split("_")[-1]
            await save_user_setting(user_id, "resume", resume_id)
            await bot.send_message(user_id, "Резюме сохранено 👍")

        await bot(call.answer())
        return {"ok": True}

    # ────────── Текстовые сообщения ──────────
    if update.message and update.message.text:
        msg = update.message
        user_id = msg.from_user.id
        text = msg.text.strip()

        # гарантируем наличие пользователя в БД
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users(chat_id) VALUES (?)",
                (user_id,),
            )
            await db.commit()

        # ─── Команды (начинаются с /) ───
        if text.startswith("/"):
            if text == "/start":
                auth_url = build_oauth_url(user_id)
                await bot.send_message(
                    user_id,
                    f"Авторизуйтесь: {auth_url}",
                )
            elif text == "/settings":
                await set_pending(user_id, None)
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT key, value FROM user_settings WHERE tg_user = ?",
                        (user_id,),
                    )
                    settings = await cur.fetchall()
                if settings:
                    msg_text = "Ваши настройки:\n" + "\n".join(
                        f"{k}: {v}" for k, v in settings
                    )
                else:
                    msg_text = "У вас ещё нет сохранённых настроек."
                await bot.send_message(
                    user_id, msg_text, reply_markup=build_settings_keyboard()
                )
            elif text == "/cancel":
                await set_pending(user_id, None)
                await bot.send_message(user_id, "Действие отменено.")
            else:
                await bot.send_message(user_id, "Неизвестная команда.")
            return {"ok": True}

        # ─── Обработка ожидаемого ввода ───
        pending = await get_pending(user_id)
        if pending:
            # ----------- Регион -----------
            if pending == "region":
                suggestions = await hh_api.get_area_suggestions(text)
                match = next(
                    (a for a in suggestions if text.lower() == a.name.lower()), None
                )
                if match:
                    await save_user_setting(user_id, "region", match.id)
                    await set_pending(user_id, None)

                    await bot.send_message(
                        user_id, f"✅ Регион установлен: {match.name}"
                    )
                    await bot.send_message(
                        user_id,
                        "Ваши настройки:",
                        reply_markup=build_settings_keyboard(),
                    )
                    return {"ok": True}

                # если не найдено точное совпадение — показываем подсказки
                kb_rows = [
                    [
                        types.InlineKeyboardButton(
                            area.name, callback_data=f"region_suggest_{area.id}"
                        )
                    ]
                    for area in suggestions[:6]
                ]
                await bot.send_message(
                    user_id,
                    "❓ Уточните регион, выберите из списка:",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_rows),
                )
                return {"ok": True}

            # ----------- График -----------
            if pending == "schedule":
                match = next(
                    (s for s in SCHEDULE_SUGGESTIONS if text.lower() == s.lower()),
                    None,
                )
                if match:
                    await save_user_setting(user_id, "schedule", match)
                    await set_pending(user_id, None)
                    await bot.send_message(
                        user_id, f"✅ График работы установлен: {match}"
                    )
                    await bot.send_message(
                        user_id,
                        "Ваши настройки:",
                        reply_markup=build_settings_keyboard(),
                    )
                    return {"ok": True}

                kb_rows = [
                    [
                        types.InlineKeyboardButton(
                            val, callback_data=f"schedule_suggest_{val}"
                        )
                    ]
                    for val in SCHEDULE_SUGGESTIONS[:6]
                ]
                await bot.send_message(
                    user_id,
                    "❓ Уточните график, выберите из списка:",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_rows),
                )
                return {"ok": True}

            # ----------- Формат работы -----------
            if pending == "work_format":
                match = next(
                    (s for s in WORK_FORMAT_SUGGESTIONS if text.lower() == s.lower()),
                    None,
                )
                if match:
                    await save_user_setting(user_id, "work_format", match)
                    await set_pending(user_id, None)
                    await bot.send_message(
                        user_id, f"✅ Формат работы установлен: {match}"
                    )
                    await bot.send_message(
                        user_id,
                        "Ваши настройки:",
                        reply_markup=build_settings_keyboard(),
                    )
                    return {"ok": True}

                kb_rows = [
                    [
                        types.InlineKeyboardButton(
                            val, callback_data=f"work_format_suggest_{val}"
                        )
                    ]
                    for val in WORK_FORMAT_SUGGESTIONS[:6]
                ]
                await bot.send_message(
                    user_id,
                    "❓ Уточните формат работы, выберите из списка:",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_rows),
                )
                return {"ok": True}

            # ----------- Зарплата -----------
            if pending == "salary":
                if text.isdigit():
                    await save_user_setting(user_id, "salary", text)
                    await set_pending(user_id, None)
                    await bot.send_message(user_id, "✅ Зарплата установлена.")
                    await bot.send_message(
                        user_id,
                        "Ваши настройки:",
                        reply_markup=build_settings_keyboard(),
                    )
                    return {"ok": True}

                kb_rows = [
                    [
                        types.InlineKeyboardButton(
                            val, callback_data=f"salary_suggest_{val}"
                        )
                    ]
                    for val in SALARY_SUGGESTIONS[:6]
                ]
                await bot.send_message(
                    user_id,
                    "❓ Введите число или выберите из вариантов:",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_rows),
                )
                return {"ok": True}

            # ----------- Тип занятости -----------
            if pending == "employment_type":
                match = next(
                    (s for s in EMPLOYMENT_TYPE_SUGGESTIONS if text.lower() == s.lower()),
                    None,
                )
                if match:
                    await save_user_setting(user_id, "employment_type", match)
                    await set_pending(user_id, None)
                    await bot.send_message(
                        user_id, f"✅ Тип занятости установлен: {match}"
                    )
                    await bot.send_message(
                        user_id,
                        "Ваши настройки:",
                        reply_markup=build_settings_keyboard(),
                    )
                    return {"ok": True}

                kb_rows = [
                    [
                        types.InlineKeyboardButton(
                            val, callback_data=f"employment_type_suggest_{val}"
                        )
                    ]
                    for val in EMPLOYMENT_TYPE_SUGGESTIONS[:6]
                ]
                await bot.send_message(
                    user_id,
                    "❓ Уточните тип занятости, выберите из списка:",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_rows),
                )
                return {"ok": True}

            # ----------- Ключевое слово -----------
            if pending == "keyword":
                await save_user_setting(user_id, "keyword", text)
                await set_pending(user_id, None)
                await bot.send_message(user_id, "Ключевое слово сохранено 👍")
                return {"ok": True}

        # Если нет ни pending, ни команды
        return {"ok": True}

    # Если апдейт не текстовый/не callback
    return {"ok": True}

# ────────────────────────────
# Вспомогательные функции
# ────────────────────────────
def build_oauth_url(tg_user: int) -> str:
    client_id = os.getenv("HH_CLIENT_ID")
    redirect_uri = os.getenv("REDIRECT_URI")
    return (
        "https://hh.ru/oauth/authorize?response_type=code"
        f"&client_id={client_id}&redirect_uri={redirect_uri}&state={tg_user}"
    )
