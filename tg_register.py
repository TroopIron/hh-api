import os
import logging
from dotenv import load_dotenv

import aiosqlite
import time
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest

from settings_utils import (
    save_user_setting,
    get_user_setting,
    build_settings_keyboard,
    set_pending,
    get_pending,
)
from resume_utils import build_resume_keyboard
import hh_api

# ────────── базовая инициализация ──────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN not set")

bot = Bot(token=BOT_TOKEN)
app = FastAPI()

DB_PATH = "tg_users.db"

# ────────── helpers ──────────
async def get_user_token(tg_user: int) -> str | None:
    """
    Читаем access_token из таблицы user_tokens.
    Возвращаем None, если запись не найдена.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT access_token FROM user_tokens WHERE tg_user = ?",
            (tg_user,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


# ────────── подсказки ──────────
SCHEDULE_SUGGESTIONS = ["полный день", "гибкий график", "сменный график"]
WORK_FORMAT_SUGGESTIONS = ["дистанционно", "офис", "гибрид"]
EMPLOYMENT_TYPE_SUGGESTIONS = ["полная", "частичная", "проектная", "стажировка"]

MULTI_KEYS = {
    "schedule": SCHEDULE_SUGGESTIONS,
    "work_format": WORK_FORMAT_SUGGESTIONS,
    "employment_type": EMPLOYMENT_TYPE_SUGGESTIONS,
}

# ────────── helpers ──────────

def build_inline_suggestions(
    values: list[str],
    prefix: str,
    selected: set[str] | None = None,
    with_back: bool = False,
):
    """Собирает клавиатуру‑однострочник; отмечает выбранные чек‑марк."""
    selected = selected or set()
    rows = [
        [
            types.InlineKeyboardButton(
                text=("✅ " if v in selected else "") + v,
                callback_data=f"{prefix}_{v}",
            )
        ]
        for v in values
    ]
    if with_back:
        rows.append([
            types.InlineKeyboardButton(
                text="⬅️ Назад", callback_data="back_settings"
            )
        ])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


async def toggle_multi_value(user_id: int, key: str, value: str) -> set[str]:
    curr = await get_user_setting(user_id, key) or ""
    items = {v.strip() for v in curr.split(",") if v.strip()}
    if value in items:
        items.remove(value)
    else:
        items.add(value)
    await save_user_setting(user_id, key, ",".join(items))
    return items


def build_oauth_url(tg_user: int) -> str:
    return (
        "https://hh.ru/oauth/authorize?response_type=code"
        f"&client_id={os.getenv('HH_CLIENT_ID')}"
        f"&redirect_uri={os.getenv('REDIRECT_URI')}"
        f"&state={tg_user}"
    )


async def safe_edit_markup(message: types.Message, markup: types.InlineKeyboardMarkup | None = None):
    """Обновить reply_markup; игнорировать BadRequest, если не изменилось."""
    try:
        await bot.edit_message_reply_markup(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=markup,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def safe_edit_text(message: types.Message, text: str,
                         markup: types.InlineKeyboardMarkup | None):
    """Безопасно обновить текст сообщения и клавиатуру."""
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=markup,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def get_settings_msg_id(uid: int) -> int | None:
    """Возвращает сохранённый msg_id сообщения настроек."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute(
                "SELECT settings_msg_id FROM users WHERE chat_id = ?",
                (uid,),
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None
        except aiosqlite.OperationalError as e:
            if "no such column" in str(e).lower():
                await db.execute(
                    "ALTER TABLE users ADD COLUMN settings_msg_id INTEGER"
                )
                await db.commit()
                return None
            raise


async def set_settings_msg_id(uid: int, msg_id: int) -> None:
    """Сохраняет msg_id сообщения настроек."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "UPDATE users SET settings_msg_id = ? WHERE chat_id = ?",
                (msg_id, uid),
            )
        except aiosqlite.OperationalError as e:
            if "no such column" in str(e).lower():
                await db.execute(
                    "ALTER TABLE users ADD COLUMN settings_msg_id INTEGER"
                )
                await db.execute(
                    "UPDATE users SET settings_msg_id = ? WHERE chat_id = ?",
                    (msg_id, uid),
                )
        await db.commit()


async def safe_edit_text_by_id(
    uid: int,
    msg_id: int | None,
    text: str,
    markup: types.InlineKeyboardMarkup | None,
):
    """Редактирует сообщение по id, отправляя новое при ошибке."""
    if msg_id is None:
        new_msg = await bot.send_message(uid, text, reply_markup=markup)
        await set_settings_msg_id(uid, new_msg.message_id)
        return
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=uid,
            message_id=msg_id,
            reply_markup=markup,
        )
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message to edit not found" in err:
            new_msg = await bot.send_message(uid, text, reply_markup=markup)
            await set_settings_msg_id(uid, new_msg.message_id)
        elif "message is not modified" not in err:
            raise


async def safe_delete(message: types.Message) -> None:
    "Пытаемся удалить сообщение пользователя, не роняя обработчик."
    try:
        await message.delete()
    except TelegramBadRequest:
        # например, если бот не админ или сообщение старше 48 ч
        pass
    except Exception:
        pass


# ────────── FastAPI lifecycle ──────────
@app.on_event("startup")
async def _startup():
    webhook = os.getenv("WEBHOOK_URL")
    if webhook:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(webhook)
        logger.info("Webhook set: %s", webhook)


@app.on_event("shutdown")
async def _shutdown():
    await bot.session.close()


# ────────── main webhook ──────────
@app.post("/bot{token:path}")
async def telegram_webhook(request: Request, token: str):
    if token != BOT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    update = types.Update(**await request.json())

    # ===== CALLBACKS =====
    if update.callback_query:
        call = update.callback_query
        uid = call.from_user.id
        data = call.data

        # ensure user row exists
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO users(chat_id) VALUES (?)", (uid,))
            await db.commit()

        if data == "back_settings":
            smsg = await get_settings_msg_id(uid)
            await safe_edit_text_by_id(
                uid,
                smsg,
                "Ваши фильтры:",
                build_settings_keyboard(),
            )
            await bot.answer_callback_query(call.id)
            return {"ok": True}

        # ---------- запуск фильтров ----------
        if data.startswith("filter_"):
            fkey = data.split("_", 1)[1]

            if fkey == "region":
                await set_pending(uid, "region")
                await safe_edit_text(call.message, "Введите название региона:", None)
                return {"ok": True}

            if fkey == "salary":
                await set_pending(uid, "salary")
                await safe_edit_text(call.message, "Введите минимальную зарплату (число):", None)
                return {"ok": True}

            if fkey in MULTI_KEYS:
                selection = await get_user_setting(uid, fkey) or ""
                sel_set = {i.strip() for i in selection.split(",") if i.strip()}
                await safe_edit_text(
                    call.message,
                    f"Выберите {fkey.replace('_', ' ')} (можно несколько):",
                    build_inline_suggestions(
                        MULTI_KEYS[fkey], f"{fkey}_suggest", sel_set, with_back=True
                    ),
                )
                return {"ok": True}

        # ---------- мультивыбор ----------
        for m in MULTI_KEYS:
            prefix = f"{m}_suggest_"
            if data.startswith(prefix):
                val = data[len(prefix):]
                sel_set = await toggle_multi_value(uid, m, val)
                await safe_edit_markup(
                    call.message,
                    build_inline_suggestions(
                        MULTI_KEYS[m], f"{m}_suggest", sel_set, with_back=True
                    ),
                )
                await bot(call.answer("✓"))
                return {"ok": True}


        # ---------- region из suggestions ----------
        if data.startswith("region_suggest_"):
            area_id = int(data.split("_")[-1])
            await save_user_setting(uid, "region", area_id)
            await safe_edit_markup(call.message, None)
            await bot(call.answer("Сохранено"))
            return {"ok": True}

        # ---------- выбор резюме ----------
        if data.startswith("select_resume_"):
            rid = data.split("_")[-1]
            await save_user_setting(uid, "resume", rid)
            await bot(call.answer("Резюме сохранено"))
            return {"ok": True}

        await bot(call.answer())  # fallback
        return {"ok": True}

    # ===== TEXT =====
    if update.message and update.message.text:
        msg = update.message
        uid = msg.from_user.id
        text = msg.text.strip()
        pending = await get_pending(uid)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO users(chat_id) VALUES (?)", (uid,))
            await db.commit()

        try:
            # ---------- commands ----------
            if text.startswith("/"):
                if text == "/start":
                    token = await get_user_token(uid)
                    if token:
                        await bot.send_message(uid, "Вы уже авторизованы ✅")
                    else:
                        await bot.send_message(uid, f"Авторизуйтесь: {build_oauth_url(uid)}")
                    return {"ok": True}

                if text == "/settings":
                    await set_pending(uid, None)
                    msg = await bot.send_message(
                        uid, "Ваши фильтры:", reply_markup=build_settings_keyboard()
                    )
                    await set_settings_msg_id(uid, msg.message_id)
                    return {"ok": True}

            if pending == "region":
                await save_user_setting(uid, "region", text)
                await set_pending(uid, None)
                msg_id = await get_settings_msg_id(uid)
                await safe_edit_text_by_id(
                    uid, msg_id, "Ваши фильтры:", build_settings_keyboard()
                )
                return {"ok": True}

            if pending == "salary" and text.isdigit():
                await save_user_setting(uid, "salary", text)
                await set_pending(uid, None)
                msg_id = await get_settings_msg_id(uid)
                await safe_edit_text_by_id(
                    uid, msg_id, "Ваши фильтры:", build_settings_keyboard()
                )
                return {"ok": True}
        finally:
            if pending:
                await safe_delete(msg)
