from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import httpx
import aiosqlite
from hh_api import HHApiClient

DB_PATH = "tg_users.db"


def build_oauth_url(tg_user: int) -> str:
    return (
        "https://hh.ru/oauth/authorize?response_type=code"
        f"&client_id={os.getenv('HH_CLIENT_ID')}"
        f"&redirect_uri={os.getenv('REDIRECT_URI')}"
        f"&state={tg_user}"
    )

async def get_user_token(tg_user: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT access_token FROM user_tokens WHERE tg_user = ?",
            (tg_user,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def build_resume_keyboard(uid: int) -> InlineKeyboardMarkup:
    """Запрашивает список резюме пользователя и строит клавиатуру."""
    token = await get_user_token(uid)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔑 Авторизоваться", url=build_oauth_url(uid))]]
    )
    if not token:
        return kb

    client = HHApiClient(token)
    try:
        resumes = await client.list_resumes()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return kb
        raise
    finally:
        await client.close()

    kb = InlineKeyboardMarkup(row_width=1)
    for item in resumes:
        rid = item.get("id")
        title = item.get("title") or item.get("profession") or "Без названия"
        kb.add(InlineKeyboardButton(title, callback_data=f"select_resume_{rid}"))
    kb.add(InlineKeyboardButton(text="⬅️ В меню", callback_data="back_menu"))
    return kb
