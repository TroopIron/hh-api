import os, aiosqlite, httpx
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
DB_PATH   = "tg_users.db"

async def _get_all_chats() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("SELECT chat_id FROM users")
    return [r[0] for r in rows]

async def send_vacancy(title: str, url: str):
    text = f"📌 <b>{title}</b>\n{url}"
    payload = {
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        for chat in await _get_all_chats():
            await client.post(api, data={**payload, "chat_id": chat, "text": text})