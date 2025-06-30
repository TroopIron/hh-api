import aiosqlite, asyncio

DB_PATH = "tg_users.db"

async def migrate():
    async with aiosqlite.connect(DB_PATH) as db:
        # отдельная таблица «ключ-значение» на пользователя
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_settings(
            tg_user INTEGER,
            key     TEXT,
            value   TEXT,
            PRIMARY KEY (tg_user, key)
        )
        """)
        await db.commit()
    print("✅  Таблица user_settings готова")

asyncio.run(migrate())