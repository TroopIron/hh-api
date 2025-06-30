from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Query
from fastapi.responses import RedirectResponse
from hh_api import HHClient
from chatgpt_client import ChatGPTClient
import os
import json
import httpx
from tg_bridge import send_vacancy
# --- Клиенты больше не создаются здесь ---

# Создаем менеджер жизненного цикла
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код здесь выполняется ПРИ ЗАПУСКЕ приложения
    print("Приложение запускается, инициализируем клиенты...")
    client_id = os.getenv('HH_CLIENT_ID')
    client_secret = os.getenv('HH_CLIENT_SECRET')
    redirect_uri = os.getenv('HH_REDIRECT_URI')

    # Создаем и "складываем" клиенты в состояние приложения
    app.state.hh_client = HHClient(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
    app.state.gpt_client = ChatGPTClient()
    print("Клиенты инициализированы.")

    yield  # В этот момент приложение работает и обрабатывает запросы

    # Код после yield выполняется ПРИ ОСТАНОВКЕ приложения
    # Здесь можно было бы закрыть соединения, если бы клиенты этого требовали
    print("Приложение останавливается.")


# Передаем наш менеджер в FastAPI
app = FastAPI(lifespan=lifespan)


# --- ОБНОВИТЕ ВАШИ ЭНДПОИНТЫ, ЧТОБЫ БРАТЬ КЛИЕНТЫ ИЗ request.app.state ---

@app.get('/')
def index(request: Request):
    # Получаем hh_client из состояния приложения
    hh_client = request.app.state.hh_client
    auth_url = hh_client.get_authorize_url()
    return RedirectResponse(auth_url)


@app.get("/callback")
async def callback(request: Request):
    code  = request.query_params.get("code")
    state = int(request.query_params.get("state"))   # ← tg_user

    hh_client = request.app.state.hh_client
    token = await hh_client.fetch_token(code)

    # 1) забираем список резюме
    resumes = await hh_client.get_my_resumes(token)
    first_pub = next((r for r in resumes["items"]
                      if r["access"] == "PUBLIC"), None)
    resume_id = first_pub["id"] if first_pub else None

    # 2) сохраняем в БД
    async with aiosqlite.connect("tg_users.db") as db:
        await db.execute("""INSERT OR REPLACE INTO user_tokens
                            (tg_user, access_token, refresh_token, resume_id)
                            VALUES (?,?,?,?)""",
                         (state,
                          token["access_token"],
                          token.get("refresh_token"),
                          resume_id))
        await db.commit()

    return {"status": "authorized", "resume": resume_id}


@app.get('/search')
async def search(request: Request, text: str = Query(..., description="Текст для поиска вакансий")):
    # Получаем hh_client из состояния приложения
    hh_client = request.app.state.hh_client
    token = json.load(open('token.json'))['access_token']
    items = await hh_client.search_vacancies(token, text=text)
    return {
        "found": len(items),
        "items": items
    }

@app.get("/resumes")
async def get_resumes(request: Request):
    try:
        hh_client = request.app.state.hh_client
        token = json.load(open('token.json'))['access_token']
        resumes = await hh_client.get_my_resumes(token)
        return resumes
    except Exception as e:
        return {"error": str(e)}

@app.post('/auto_reply')
async def auto_reply(request: Request):
    hh_client = request.app.state.hh_client
    gpt_client = request.app.state.gpt_client
    token = json.load(open('token.json'))['access_token']

    # Жестко укажем ID твоего резюме (потом сделаем автоматический выбор)
    resume_id = "85b0ac5aff0f05ef8b0039ed1f507165623145"

    # Ищем вакансии по ключу
    vacancies = await hh_client.search_vacancies(token, text="python")

    results = []

    MAX_REPLIES = 10

    for vacancy in vacancies[:MAX_REPLIES]:
        # 1) пропускаем вакансии с тестом
        if vacancy.get("has_test"):
            print(f"⏭ Пропускаю вакансию с тестом {vacancy['id']}")
            continue

        vacancy_id = vacancy["id"]
        title = vacancy.get("name")
        url = vacancy.get("alternate_url")

        # 2) Шлём карточку в Telegram  👈 ВОТ СЮДА
        await send_vacancy(title, url)

        print(f"→ Пробую отклик на «{title}» ({vacancy_id})")

        # 3) Генерируем письмо-заглушку
        description = vacancy["snippet"].get("requirement") or "Описание отсутствует"
        message = await gpt_client.generate_cover_letter(
            description,
            "Мой опыт в Python-разработке..."
        )

        # 4) Пытаемся откликнуться
        try:
            code = await hh_client.respond_to_vacancy(
                token, resume_id, vacancy_id, message
            )
            results.append({"vacancy_id": vacancy_id, "status": code})
        except httpx.HTTPStatusError as e:
            err_text = e.response.text
            print("‼️ HH error:", err_text)
            results.append({"vacancy_id": vacancy_id, "error": err_text})

    return {"results": results}

# DEBUG: выведем в консоль все маршруты
for route in app.routes:
    print(route.path, route.methods)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)