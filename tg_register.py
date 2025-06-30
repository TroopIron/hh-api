# tg_register.py
import os, gzip, zlib, json, httpx, aiosqlite, urllib.parse
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from urllib.parse import unquote
from hh_api import HHClient
from settings_utils import (
    build_settings_keyboard, FILTER_KEYBOARD,
    build_multiselect_kb, EMPLOYMENT_VALUES, SCHEDULE_VALUES,
    set_pending, get_pending,
    set_user_setting, get_user_setting,
    FIELD_INFO
)
from pathlib import Path

load_dotenv()
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
DB_PATH = str(Path(__file__).with_name("tg_users.db"))

# ――― временный выбор резюме «только для одного отклика»
TEMP_RESUME: dict[int, str] = {}   # tg_user -> resume_id

app = FastAPI()

# ══════════════════════════════════════════════════════════════
# 0.  /callback  (OAuth HH.ru)
# ══════════════════════════════════════════════════════════════
@app.get("/callback")
async def hh_callback(code: str, state: int):
    """
    state = tg_user – мы передавали его в параметре &state= …
    """
    hh = HHClient(
        os.getenv("HH_CLIENT_ID"),
        os.getenv("HH_CLIENT_SECRET"),
        os.getenv("HH_REDIRECT_URI"),
    )

    # 1. получаем токен
    token = await hh.exchange_code(code)

    # 2. сразу (!) сообщаем пользователю, что авторизация прошла
    await tg_request("sendMessage", {
        "chat_id": state,              # chat_id == tg_user (приватный чат)
        "text": "✅ Доступ к аккаунту HH получен!"
    })

    # 3. вытаскиваем резюме
    resumes = await hh.get_my_resumes(token["access_token"])
    if not resumes:
        # … как было …
        return PlainTextResponse("Нет опубликованных резюме…", status_code=200)

    # 4. одно резюме – сохраняем и всё
    if len(resumes) == 1:
        await save_user_token(state, token, resumes[0]["id"])
        # можно дополнительно подсказать команды
        await tg_request("sendMessage", {
            "chat_id": state,
            "text": (
                "/browse — смотреть вакансии\n"
                "/settings — настроить фильтры"
            )
        })
        return PlainTextResponse("OK", status_code=200)

    # 5. резюме несколько – сохраняем токен без resume_id
    await save_user_token(state, token)            # resume_id=None
    # показываем клавиатуру выбора
    await tg_request("sendMessage", {
        "chat_id": state,
        "text":  "Выберите резюме, которое бот будет использовать:",
        "reply_markup": build_resume_keyboard(resumes)
    })
    return PlainTextResponse("WAITING", status_code=200)


# ══════════════════════════════════════════════════════════════
# 1.  DB helpers
# ══════════════════════════════════════════════════════════════
@app.on_event("startup")
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            tg_user INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS queues(
            tg_user INTEGER PRIMARY KEY,
            cursor  INTEGER DEFAULT 0,
            payload TEXT
        );
        CREATE TABLE IF NOT EXISTS user_tokens(
            tg_user       INTEGER PRIMARY KEY,
            access_token  TEXT,
            refresh_token TEXT,
            resume_id     TEXT          -- ← уже есть
        );

        /*  ➤ ДОБАВЬТЕ ВОТ ЭТО  */
        CREATE TABLE IF NOT EXISTS user_settings(
            tg_user INTEGER NOT NULL,
            key     TEXT,
            field   TEXT    NOT NULL,
            value   TEXT,
            PRIMARY KEY (tg_user, field)
        );
        """)

        # 2) проверяем, есть ли столбец resume_id – если нет, добавляем
        cur = await db.execute("PRAGMA table_info(user_tokens)")
        cols = [row[1] async for row in cur]          # row[1] == имя колонки
        if "resume_id" not in cols:
            await db.execute("ALTER TABLE user_tokens ADD COLUMN resume_id TEXT")

        await db.commit()

async def db_fetchone(db, sql: str, args: tuple):
    cur = await db.execute(sql, args)
    row = await cur.fetchone()
    await cur.close()
    return row

async def save_user_token(tg_user: int,
                          token: dict,
                          resume_id: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_tokens
                (tg_user, access_token, refresh_token, resume_id)
            VALUES (?,?,?,?)
            ON CONFLICT(tg_user) DO UPDATE SET
                access_token  = excluded.access_token,
                refresh_token = excluded.refresh_token,
                -- если прилетел новый resume_id – берём его,
                -- иначе оставляем старый (user_tokens.resume_id)
                resume_id     = COALESCE(excluded.resume_id,
                                         user_tokens.resume_id)
            """,
            (
                tg_user,
                token.get("access_token"),
                token.get("refresh_token"),
                resume_id,
            ),
        )
        await db.commit()

async def notify_ok(tg_user:int):
    async with aiosqlite.connect(DB_PATH) as db:
        row = await db_fetchone(db,
            "SELECT chat_id FROM users WHERE tg_user=?", (tg_user,))
    if row:
        await tg_request("sendMessage",{
            "chat_id": row[0],
            "text": "✅ Авторизация завершена! /browse — вакансии, /settings — фильтры"
        })

async def save_chat(tg_user:int, chat_id:int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users(tg_user,chat_id) VALUES(?,?)",
            (tg_user, chat_id))
        await db.commit()

# ══════════════════════════════════════════════════════════════
# 2.  Telegram / HH helpers
# ══════════════════════════════════════════════════════════════
def decode_update(raw: bytes) -> dict|None:
    for attempt in (raw, gzip.decompress, zlib.decompress):
        try:
            chunk = attempt(raw) if callable(attempt) else attempt
            return json.loads(chunk.decode("utf-8"))
        except Exception:
            pass
    return None

def build_auth_url(tg_user:int)->str:
    hh = HHClient(os.getenv("HH_CLIENT_ID"),
                  os.getenv("HH_CLIENT_SECRET"),
                  os.getenv("HH_REDIRECT_URI"))
    return hh.get_authorize_url()+"&state="+str(tg_user)

async def tg_request(method:str, payload:dict):
    url=f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with httpx.AsyncClient() as c:
        r=await c.post(url,json=payload)
        r.raise_for_status()

async def hh_area_suggest(q:str):
    async with httpx.AsyncClient() as c:
        r=await c.get("https://api.hh.ru/suggests/areas",
                      params={"text":q,"locale":"RU"},timeout=10)
        r.raise_for_status()
        d=r.json()
    return [(i["text"], int(i["id"])) for i in d["items"][:5]]

def build_area_keyboard(pairs):
    rows = [[{"text":t,"callback_data":f"choose_area:{aid}"}] for t,aid in pairs]
    rows.append([{"text":"⬅️ Назад","callback_data":"back:filters"}])
    return {"inline_keyboard":rows}

def build_resume_keyboard(resumes:list[dict], prefix="choose_resume") -> dict:
    rows = [[{
        "text": f"📄 {r.get('title') or r.get('profession')}",
        "callback_data": f"{prefix}:{r['id']}"
    }] for r in resumes]
    return {"inline_keyboard": rows}

# ══════════════════════════════════════════════════════════════
# 3.  Вакансии: очередь + карточка
# ══════════════════════════════════════════════════════════════
async def save_queue(tg_user:int, items):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT OR REPLACE INTO queues
                            (tg_user,cursor,payload) VALUES(?,0,?)""",
                         (tg_user,json.dumps(items)))
        await db.commit()

async def pop_next(tg_user:int):
    async with aiosqlite.connect(DB_PATH) as db:
        row = await db_fetchone(db,
            "SELECT cursor,payload FROM queues WHERE tg_user=?", (tg_user,))
    if not row: return None
    cur,payload = row
    items = json.loads(payload)
    if cur>=len(items): return None
    vac=items[cur]
    await set_cursor(tg_user,cur+1)
    return vac

async def set_cursor(tg_user:int, idx:int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE queues SET cursor=? WHERE tg_user=?",(idx,tg_user))
        await db.commit()

async def clear_queue(tg_user:int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM queues WHERE tg_user=?", (tg_user,))
        await db.commit()

def build_card(v):
    salary = v.get("salary") or {}
    sal_txt = ("до "+str(salary["to"]) if salary.get("to")
               else str(salary["from"])+" ₽+" if salary.get("from")
               else "не указана")
    desc = (v.get("snippet",{}).get("requirement")
            or v.get("snippet",{}).get("responsibility") or "")
    desc = (desc[:300]+"…") if len(desc)>300 else desc
    text = f"<b>{v['name']}</b>\n💰 {sal_txt}\n{desc}\n{v['alternate_url']}"

    kb = {"inline_keyboard":[
        [{"text":"🔔 Откликнуться","callback_data":f"resp:{v['id']}"}],
        [{"text":"➡️ Дальше","callback_data":"next"}],
        [{"text":"❌ Стоп","callback_data":"stop"}]
    ]}
    return text,kb

async def send_card(chat_id,tg_user,v):
    txt,kb = build_card(v)
    await tg_request("sendMessage",{
        "chat_id":chat_id,"text":txt,"parse_mode":"HTML",
        "disable_web_page_preview":False,"reply_markup":kb})

async def edit_card(chat_id,msg_id,v):
    txt,kb = build_card(v)
    try:
        await tg_request("editMessageText",{
            "chat_id":chat_id,"message_id":msg_id,
            "text":txt,"parse_mode":"HTML",
            "disable_web_page_preview":False,"reply_markup":kb})
    except httpx.HTTPStatusError as e:
        if e.response.status_code==400 and "message is not modified" in e.response.text.lower():
            return
        raise

# ══════════════════════════════════════════════════════════════
# 4.  Фильтры → HH params
# ══════════════════════════════════════════════════════════════
async def collect_filters(tg_user:int):
    res={}
    if (v:=await get_user_setting(tg_user,"salary_min")): res["salary"]=v
    if (v:=await get_user_setting(tg_user,"keyword")):    res["text"]=v
    if (v:=await get_user_setting(tg_user,"region")):     res["area"]=v
    if (v:=await get_user_setting(tg_user,"employment")): res["employment"]=v.split(",")
    if (v:=await get_user_setting(tg_user,"schedule")):   res["schedule"]=v.split(",")
    return res

# ══════════════════════════════════════════════════════════════
# 5.  Отклик
# ══════════════════════════════════════════════════════════════
async def respond_flow(tg_user:int, vacancy_id:str):
    async with aiosqlite.connect(DB_PATH) as db:
        row = await db_fetchone(db,
            "SELECT access_token,resume_id FROM user_tokens WHERE tg_user=?",
            (tg_user,))
    if not row:
        raise RuntimeError("Сначала авторизуйтесь через /start")
    access_token, resume_default = row
    resume_id = TEMP_RESUME.pop(tg_user, None) or resume_default
    if not resume_id:
        raise RuntimeError("Сначала выберите резюме через /resumes")

    cover = "Хочу у вас работать. Ознакомьтесь с моим резюме."
    hh = HHClient("","","")
    await hh.respond_to_vacancy(access_token, resume_id, vacancy_id, cover)

# ══════════════════════════════════════════════════════════════
# 6.  Web-hook
# ══════════════════════════════════════════════════════════════
@app.post("/bot{token:path}")
async def telegram_webhook(token: str, request: Request):
    # 0. базовая проверка ------------------------------------------------
    if unquote(token) != BOT_TOKEN:
        raise HTTPException(403, "bad token")

    data = decode_update(await request.body())
    if data is None:
        raise HTTPException(400, "decode error")

    # ────────────────────────────────────────────────────────────────────
    # 1. CALLBACK-QUERY
    # ────────────────────────────────────────────────────────────────────
    if (cq := data.get("callback_query")):
        chat_id = cq["message"]["chat"]["id"]
        tg_user = cq["from"]["id"]
        act     = cq["data"]

        # 1.1 выбор резюме из /resumes  ----------------------------------
        if act.startswith("choose_resume:"):
            resume_id = act.split(":", 1)[1]

            #  ❗  Меняем ТОЛЬКО resume_id, не трогаем access_token
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE user_tokens SET resume_id = ? WHERE tg_user = ?",
                    (resume_id, tg_user)
                )
                await db.commit()

            await tg_request("editMessageText", {
                "chat_id": chat_id,
                "message_id": cq["message"]["message_id"],
                "text": "✅ Резюме по умолчанию сохранено!"
            })
            return {"ok": True}

        # 1.2 «Дальше» ----------------------------------------------------
        if act == "next":
            vac = await pop_next(tg_user)
            if vac:
                await edit_card(chat_id, cq["message"]["message_id"], vac)
            else:
                await tg_request("answerCallbackQuery", {
                    "callback_query_id": cq["id"],
                    "text": "Дальше вакансий нет"
                })
            return {"ok": True}

        # 1.3 отклик ------------------------------------------------------
        if act.startswith("resp:"):
            vid = act.split(":", 1)[1]
            try:
                await respond_flow(tg_user, vid)
                txt = "✅ Отклик отправлен!"
            except Exception as e:
                txt = f"❗ HH: {e}"
            await tg_request("answerCallbackQuery", {
                "callback_query_id": cq["id"],
                "text": txt
            })
            return {"ok": True}

        # 1.4 «Стоп» ------------------------------------------------------
        if act == "stop":
            await clear_queue(tg_user)
            await tg_request("editMessageText", {
                "chat_id": chat_id,
                "message_id": cq["message"]["message_id"],
                "text": "Просмотр остановлен"
            })
            return {"ok": True}
            # 1.5 Открытие меню настроек
        if act.startswith("open:"):
            submenu = act.split(":", 1)[1]

            # 1.5.1 Главное меню фильтров
            if submenu == "filters":
                await tg_request("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": cq["message"]["message_id"],
                    "text": "📑 Фильтры",
                    "reply_markup": FILTER_KEYBOARD
                })

            # 1.5.2 Подменю «Регион»
            elif submenu == "region":
                # здесь собираем вашу клавиатуру с регионами
                # например, вы заранее в settings_utils.py сделали REGION_KEYBOARD
                await tg_request("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": cq["message"]["message_id"],
                    "text": "🌍 Выберите регион:",
                    "reply_markup": REGION_KEYBOARD
                })

            # 1.5.3 Подменю «Зарплата»
            elif submenu == "salary":
                await tg_request("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": cq["message"]["message_id"],
                    "text": "💰 Установите диапазон зарплаты:",
                    "reply_markup": SALARY_KEYBOARD
                })

            # 1.5.4 Ввод ключевого слова
            elif submenu == "keyword":
                # переводим бота в режим ожидания текста
                await set_pending(tg_user, "keyword")
                await tg_request("answerCallbackQuery", {
                    "callback_query_id": cq["id"],
                    "text": "Введите ключевое слово для поиска"
                })

            # 1.5.5 Тип занятости
            elif submenu == "employment":
                await tg_request("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": cq["message"]["message_id"],
                    "text": "⚙️ Выберите тип занятости:",
                    "reply_markup": EMPLOYMENT_KEYBOARD
                })

            # 1.5.6 График работы
            elif submenu == "schedule":
                await tg_request("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": cq["message"]["message_id"],
                    "text": "🕒 Выберите график работы:",
                    "reply_markup": SCHEDULE_KEYBOARD
                })

            # 1.5.7 «Назад» в предыдущее меню фильтров
            elif submenu == "back":
                await tg_request("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": cq["message"]["message_id"],
                    "text": "📑 Фильтры",
                    "reply_markup": FILTER_KEYBOARD
                })

            return {"ok": True}


        # … добавьте здесь обработчики фильтров / меню (если у вас были) …

    # ────────────────────────────────────────────────────────────────────
    # 2. MESSAGE (обычный текст)
    # ────────────────────────────────────────────────────────────────────
    if (msg := data.get("message")):
        chat_id = msg["chat"]["id"]
        tg_user = msg["from"]["id"]
        text    = msg.get("text", "")
        await save_chat(tg_user, chat_id)

        # 2.1 /start ------------------------------------------------------
        if text.startswith("/start"):
            async with aiosqlite.connect(DB_PATH) as db:
                row = await db_fetchone(
                    db,
                    "SELECT 1 FROM user_tokens WHERE tg_user = ?",
                    (tg_user,)
                )

            if not row:                                 # ещё не авторизован
                url = build_auth_url(tg_user)
                await tg_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": ("Чтобы я мог откликаться от твоего имени:\n"
                             f'<a href="{url}">👉 Начать автоотклики</a>'),
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                })
                return {"ok": True}

            # авторизация уже есть
            await tg_request("sendMessage", {
                "chat_id": chat_id,
                "text": ("✅ Бот уже авторизован.\n"
                         "/browse — посмотреть вакансии\n"
                         "/settings — настроить фильтры\n"
                         "/resumes — выбрать резюме")
            })
            return {"ok": True}

        # 2.2 /resumes ----------------------------------------------------
        if text.startswith("/resumes"):
            async with aiosqlite.connect(DB_PATH) as db:
                row = await db_fetchone(
                    db,
                    "SELECT access_token FROM user_tokens WHERE tg_user = ?",
                    (tg_user,)
                )
            if not row:
                await tg_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": "Сначала авторизуйтесь через /start"
                })
                return {"ok": True}

            hh = HHClient(os.getenv("HH_CLIENT_ID"),
                          os.getenv("HH_CLIENT_SECRET"),
                          os.getenv("HH_REDIRECT_URI"))
            resumes = await hh.get_my_resumes(row[0])
            if not resumes:
                await tg_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": "У вас нет опубликованных резюме."
                })
                return {"ok": True}

            await tg_request("sendMessage", {
                "chat_id": chat_id,
                "text": "Выберите резюме по умолчанию:",
                "reply_markup": build_resume_keyboard(resumes)
            })
            return {"ok": True}
        # 2.3 /settings ---------------------------------------------------
        if text.startswith("/settings"):
            kb = build_settings_keyboard()
            await tg_request("sendMessage", {
                "chat_id": chat_id,
                "text": "⚙️ Настройки поиска вакансий",
                "reply_markup": kb
            })
            return {"ok": True}

        # 2.3 /browse -----------------------------------------------------
        if text.startswith("/browse"):
            filters = await collect_filters(tg_user)
            async with aiosqlite.connect(DB_PATH) as db:
                row = await db_fetchone(
                    db,
                    "SELECT access_token FROM user_tokens WHERE tg_user = ?",
                    (tg_user,)
                )
            if not row:
                await tg_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": "Сначала авторизуйтесь через /start"
                })
                return {"ok": True}

            hh = HHClient("", "", "")
            try:
                items = await hh.search_vacancies(row[0], per_page=10, **filters)
            except Exception as e:
                await tg_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❗ HH error: {e}"
                })
                return {"ok": True}

            if not items:
                await tg_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": "По заданным фильтрам ничего не найдено."
                })
                return {"ok": True}

            await save_queue(tg_user, items)
            await send_card(chat_id, tg_user, items[0])
            await set_cursor(tg_user, 1)
            return {"ok": True}

        # … здесь остаётся обработка /settings и pending-полей …

    # ────────────────────────────────────────────────────────────────────
    return {"ok": True}