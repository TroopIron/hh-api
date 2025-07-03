from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import aiosqlite
from hh_api import HHClient

DB_PATH = "tg_users.db"

async def _get_user_token(tg_user: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT access_token FROM user_tokens WHERE tg_user = ?",
            (tg_user,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def build_resume_keyboard(uid: int) -> InlineKeyboardMarkup:
    """Запрашивает список резюме пользователя и строит клавиатуру."""
    token = await _get_user_token(uid)
    if not token:
        return InlineKeyboardMarkup(inline_keyboard=[])

    client = HHClient(
        os.getenv("HH_CLIENT_ID"),
        os.getenv("HH_CLIENT_SECRET"),
        os.getenv("REDIRECT_URI"),
    )
    try:
        resumes = await client.list_resumes(token)
    finally:
        await client.close()

    kb = InlineKeyboardMarkup(row_width=1)
    for item in resumes:
        rid = item.get("id")
        title = item.get("title") or item.get("profession") or "Без названия"
        kb.add(InlineKeyboardButton(title, callback_data=f"select_resume_{rid}"))
    return kb
