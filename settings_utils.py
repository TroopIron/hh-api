import aiosqlite

DB_PATH = "tg_users.db"

# ---------------------------------------------------------------------------
async def set_user_setting(tg_user: int, key: str, value: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        if value is None:
            await db.execute(
                "DELETE FROM user_settings WHERE tg_user=? AND key=?",
                (tg_user, key)
            )
        else:
            await db.execute("""
                INSERT INTO user_settings(tg_user, key, value)
                VALUES(?,?,?)
                ON CONFLICT(tg_user, key)
                DO UPDATE SET value=excluded.value
            """, (tg_user, key, value))
        await db.commit()

async def get_user_setting(tg_user: int, key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT value FROM user_settings WHERE tg_user=? AND key=?",
            (tg_user, key)
        )
        row = await cursor.fetchone()
    return row[0] if row else None

# ------ «pending» -----------------------------------------------------------
async def set_pending(tg_user: int, field: str | None):
    await set_user_setting(tg_user, "pending", field)

async def get_pending(tg_user: int) -> str | None:
    return await get_user_setting(tg_user, "pending")

# ------ клавиатура (оставьте как было) --------------------------------------
def build_settings_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📑 Фильтры", "callback_data": "open:filters"}],
            [{"text": "⬅️ Назад",   "callback_data": "back:main"}]
        ]
    }

# ------ справочник полей ----------------------------------------------------
FIELD_INFO = {
    "salary_min": {
        "title": "Минимальная зарплата",
        "hint": (
            "Укажите сумму в рублях. "
            "Вакансии с указанной зарплатой ниже этого порога бот будет пропускать.\n"
            "Пример: 70000"
        ),
        "validator": str.isdigit
    },
}

# --- ↓ добавьте / замените в конце файла ------------------------------------

FILTER_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "💰 Зарплата",        "callback_data": "set:salary_min"}],
        [{"text": "🌍 Регион",          "callback_data": "set:region"}],
        [{"text": "🔎 Ключевое слово",  "callback_data": "set:keyword"}],
        [{"text": "📋 Тип занятости",   "callback_data": "sub:employment"}],
        [{"text": "🕒 График работы",   "callback_data": "sub:schedule"}],
        [{"text": "⬅️ Назад",           "callback_data": "back:settings"}]
    ]
}

EMPLOYMENT_VALUES = [
    ("Полная",   "full"),
    ("Частичная","part"),
    ("Проект",   "project"),
    ("Стажировка","probation"),
]

SCHEDULE_VALUES = [
    ("Офис",     "fullDay"),
    ("Удалёнка", "remote"),
    ("Смены",    "shift"),
    ("Гибкий",   "flexible"),
]

def build_multiselect_kb(prefix: str, options: list[tuple[str, str]], chosen: set[str]):
    rows = []
    for title, code in options:
        mark = "✅ " if code in chosen else ""
        rows.append([{
            "text": f"{mark}{title}",
            "callback_data": f"toggle:{prefix}:{code}"
        }])
    rows.append([{"text": "⬅️ Назад", "callback_data": "back:filters"}])
    return {"inline_keyboard": rows}

# --- дополняем FIELD_INFO ----------------------------------------------------
FIELD_INFO.update({
    "region": {
        "title": "Регион поиска",
        "hint":  "Введите город или область (часть названия). "
                 "Я покажу 5 ближайших совпадений для подтверждения.",
        "validator": lambda x: len(x) >= 2
    },
    "keyword": {
        "title": "Ключевое слово",
        "hint":  ("Введите ключевое слово. HH ищет по вхождению, "
                  "поэтому «маркетолог» подхватит и Digital-маркетолог, "
                  "и Директор по маркетингу."),
        "validator": lambda x: len(x) >= 3
    },
})