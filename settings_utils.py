import aiosqlite
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional

# Путь к SQLite базе
DB_PATH = "tg_users.db"

# Путь к SQLite базе\ DB_PATH = "tg_users.db"

async def set_pending(tg_user: int, field: Optional[str]):
    """
    Помечаем, что для пользователя tg_user сейчас ожидается ввод для поля field.
    Для сброса передайте field=None.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_settings (tg_user, key, value) VALUES (?, ?, ?)",
            (tg_user, "pending", field)
        )
        await db.commit()

async def get_pending(tg_user: int) -> Optional[str]:
    """
    Возвращает текущее pending-поле для пользователя или None, если ожидание не установлено.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM user_settings WHERE tg_user = ? AND key = 'pending'",
            (tg_user,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def save_user_setting(tg_user: int, key: str, value: str):
    """
    Сохраняет любое пользовательское значение (фильтр) по ключу key.
    Пример key: 'region', 'salary', 'work_format', 'employment_type', 'keyword', 'prompt'.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_settings (tg_user, key, value) VALUES (?, ?, ?)",
            (tg_user, key, value)
        )
        await db.commit()

async def get_user_setting(tg_user: int, key: str) -> Optional[str]:
    """
    Получает сохранённое значение пользователя по ключу key.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM user_settings WHERE tg_user = ? AND key = ?",
            (tg_user, key)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    kb = [
        [InlineKeyboardButton("⚙️ Настройка фильтров", callback_data="open_settings")],
        [InlineKeyboardButton("📄 Резюме", callback_data="open_resumes")],
        [InlineKeyboardButton("👁️ Просмотр фильтров", callback_data="show_filters")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def build_settings_keyboard(with_back: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура управления фильтрами."""
    rows = [
        [
            InlineKeyboardButton(text="Регион", callback_data="filter_region"),
            InlineKeyboardButton(text="График", callback_data="filter_schedule"),
        ],
        [
            InlineKeyboardButton(text="Формат работы", callback_data="filter_work_format"),
            InlineKeyboardButton(text="ЗП", callback_data="filter_salary"),
        ],
        [
            InlineKeyboardButton(text="Тип занятости", callback_data="filter_employment_type"),
            InlineKeyboardButton(text="Ключевое слово", callback_data="filter_keyword"),
        ],
    ]
    if with_back:
        rows.append([InlineKeyboardButton("⬅️ В меню", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
