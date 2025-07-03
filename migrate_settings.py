import asyncio
import aiosqlite

# Путь к файлу базы данных
DB_PATH = "tg_users.db"

async def upgrade(db: aiosqlite.Connection):
    """
    Создаёт таблицы users, user_tokens, queues и user_settings, если они не существуют.
    """
    # Таблица пользователей Telegram
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            settings_msg_id INTEGER
        );
    """
    )

    # Добавляем колонку settings_msg_id, если база старая
    async with db.execute("PRAGMA table_info(users)") as cur:
        cols = [row[1] async for row in cur]
    if "settings_msg_id" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN settings_msg_id INTEGER")

    # Таблица токенов пользователей
    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_tokens (
            tg_user       INTEGER PRIMARY KEY,
            access_token  TEXT    NOT NULL,
            refresh_token TEXT    NOT NULL,
            expires_at    INTEGER NOT NULL
        );
    """)

    # Таблица очереди вакансий
    await db.execute("""
        CREATE TABLE IF NOT EXISTS queues (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_user    INTEGER NOT NULL,
            vacancy_id TEXT    NOT NULL,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );
    """)

    # Таблица пользовательских настроек
    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            tg_user INTEGER,
            key     TEXT,
            value   TEXT,
            PRIMARY KEY (tg_user, key)
        );
    """)

    # Сохраняем изменения
    await db.commit()

async def main():
    # Подключаемся и выполняем миграцию
    async with aiosqlite.connect(DB_PATH) as db:
        await upgrade(db)
    print("Миграция успешно выполнена.")

if __name__ == "__main__":
    asyncio.run(main())
