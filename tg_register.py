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
    get_pending
)
from resume_utils import build_resume_keyboard
import hh_api

# Загрузка переменных окружения
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

@app.post("/bot{token:path}")
async def telegram_webhook(request: Request, token: str):
    # Проверка токена вебхука
    if token != BOT_TOKEN:
        logger.warning("Invalid webhook token: %s", token)
        raise HTTPException(status_code=403, detail="Invalid token")

    body = await request.json()
    update = types.Update(**body)

    # --- Inline-кнопки ---
    if update.callback_query:
        call = update.callback_query
        user_id = call.from_user.id
        # Регистрация пользователя
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO users(chat_id) VALUES (?)", (user_id,))
            await db.commit()

        data = call.data
        # Установка pending и запрос ввода
        if data == "filter_region":
            await set_pending(user_id, "region")
            await bot.send_message(user_id, "Введите название региона:")
        elif data == "filter_schedule":
            await set_pending(user_id, "schedule")
            await bot.send_message(user_id, "Введите желаемый график (например, полный день):")
        elif data == "filter_work_format":
            await set_pending(user_id, "work_format")
            await bot.send_message(user_id, "Введите формат работы (дистанционно/офис/гибрид):")
        elif data == "filter_salary":
            await set_pending(user_id, "salary")
            await bot.send_message(user_id, "Введите минимальную зарплату в рублях:")
        elif data == "filter_employment_type":
            await set_pending(user_id, "employment_type")
            await bot.send_message(user_id, "Введите тип занятости (полная/частичная):")
        elif data == "filter_keyword":
            await set_pending(user_id, "keyword")
            await bot.send_message(user_id, "Введите ключевое слово для поиска вакансий:")
        # Выбор региона из подсказок
        elif data.startswith("region_suggest_"):
            area_id = data.split("_")[-1]
            await save_user_setting(user_id, "region", area_id)
            await set_pending(user_id, None)
            await call.message.edit_reply_markup()
            await bot.send_message(user_id, "Регион сохранён 👍")
        # Выбор резюме
        elif data.startswith("select_resume_"):
            resume_id = data.split("_")[-1]
            await save_user_setting(user_id, "resume", resume_id)
            await bot.send_message(user_id, "Резюме сохранено 👍")

        await call.answer()
        return {"ok": True}

    # --- Текстовые сообщения ---
    if update.message and update.message.text:
        msg = update.message
        user_id = msg.from_user.id
        text = msg.text.strip()
        # Регистрация пользователя
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO users(chat_id) VALUES (?)", (user_id,))
            await db.commit()

        # Команды (начинаются с '/')
        if text.startswith("/"):
            if text == "/start":
                auth_url = build_oauth_url(user_id)
                await bot.send_message(
                    user_id,
                    f"Авторизуйтесь: {auth_url}",
                    disable_web_page_preview=True
                )
            elif text == "/settings":
                # Сброс pending перед показом меню
                await set_pending(user_id, None)
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT key, value FROM user_settings WHERE tg_user = ?",
                        (user_id,),
                    )
                    settings = await cur.fetchall()
                if settings:
                    msg_text = "Ваши настройки:\n" + "\n".join(f"{k}: {v}" for k, v in settings)
                else:
                    msg_text = "У вас ещё нет сохранённых настроек."
                await bot.send_message(user_id, msg_text, reply_markup=build_settings_keyboard())
            elif text == "/cancel":
                await set_pending(user_id, None)
                await bot.send_message(user_id, "Действие отменено")
            else:
                await bot.send_message(user_id, "Неизвестная команда.")
            return {"ok": True}

        # Обработка ожидаемого ввода
        pending = await get_pending(user_id)
        if pending:
            if pending == "region":
                suggestions = await hh_api.get_area_suggestions(text)
                # сразу сохраняем, если ввод содержится в названии
                match = next((a for a in suggestions if text.lower() in a.name.lower()), None)
                if match:
                    await save_user_setting(user_id, "region", match.id)
                    await set_pending(user_id, None)
                    await bot.send_message(user_id, f"Регион «{match.name}» сохранён 👍")
                else:
                    # предлагаем кнопки для выбора
                    kb_rows = [[
                        types.InlineKeyboardButton(area.name, callback_data=f"region_suggest_{area.id}")
                    ] for area in suggestions[:6]]
                    await bot.send_message(
                        user_id,
                        "Регион не найден. Выберите вариант из списка ниже:",
                        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_rows)
                    )
                return {"ok": True}

            if pending == "schedule":
                await save_user_setting(user_id, "schedule", text)
                await set_pending(user_id, None)
                await bot.send_message(user_id, "График работы сохранён 👍")
                return {"ok": True}

            if pending == "work_format":
                await save_user_setting(user_id, "work_format", text)
                await set_pending(user_id, None)
                await bot.send_message(user_id, "Формат работы сохранён 👍")
                return {"ok": True}

            if pending == "salary":
                await save_user_setting(user_id, "salary", text)
                await set_pending(user_id, None)
                await bot.send_message(user_id, "Зарплата сохранена 👍")
                return {"ok": True}

            if pending == "employment_type":
                await save_user_setting(user_id, "employment_type", text)
                await set_pending(user_id, None)
                await bot.send_message(user_id, "Тип занятости сохранён 👍")
                return {"ok": True}

            if pending == "keyword":
                await save_user_setting(user_id, "keyword", text)
                await set_pending(user_id, None)
                await bot.send_message(user_id, "Ключевое слово сохранено 👍")
                return {"ok": True}

        return {"ok": True}

    return {"ok": True}


def build_oauth_url(tg_user: int) -> str:
    client_id = os.getenv("HH_CLIENT_ID")
    redirect_uri = os.getenv("REDIRECT_URI")
    return (
        f"https://hh.ru/oauth/authorize?response_type=code"
        f"&client_id={client_id}&redirect_uri={redirect_uri}&state={tg_user}"
    )