import os
import httpx
from typing import Any, Dict, List


class HHClient:
    # Константы API
    BASE_URL = "https://api.hh.ru"
    AUTH_URL = "https://hh.ru/oauth/authorize"  # всегда hh.ru
    TOKEN_URL = "https://hh.ru/oauth/token"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        """
        Инициализация клиента.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        ua = os.getenv("HH_UA", "AutoReplyBot/1.0 (contact@example.com)")
        self.client = httpx.AsyncClient(timeout=10, headers={"User-Agent": ua})

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        Обменивает authorization code на пару токенов.
        """
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        resp = await self.client.post(self.TOKEN_URL, data=data)
        if resp.status_code != 200:
            # Логируем код и тело ответа
            import logging
            logger = logging.getLogger(__name__)
            logger.error("HH OAuth error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
        return resp.json()

    async def _auth_headers(self, access_token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    async def search_vacancies(
        self,
        access_token: str,
        text: str,
        per_page: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Поиск вакансий по тексту.
        """
        params = {"text": text, "per_page": per_page}
        resp = await self.client.get(
            f"{self.BASE_URL}/vacancies",
            params=params,
            headers=await self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def list_resumes(self, access_token: str) -> List[Dict[str, Any]]:
        """
        Получение списка резюме пользователя.
        """
        resp = await self.client.get(
            f"{self.BASE_URL}/resumes/mine",
            headers=await self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def get_vacancy(
        self,
        vacancy_id: str,
        access_token: str
    ) -> Dict[str, Any]:
        """
        Получение детальной информации о вакансии по ID.
        """
        resp = await self.client.get(
            f"{self.BASE_URL}/vacancies/{vacancy_id}",
            headers=await self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json()

    async def respond_to_vacancy(
        self,
        access_token: str,
        vacancy_id: str,
        resume_id: str,
        cover_letter: str
    ) -> Dict[str, Any]:
        """
        Отправка отклика на вакансию (создание переговоров).
        """
        payload = {
            "vacancy_id": vacancy_id,
            "resume_id": resume_id,
            "cover_letter": cover_letter,
        }
        resp = await self.client.post(
            f"{self.BASE_URL}/negotiations",
            json=payload,
            headers=await self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        """
        Закрывает HTTP-сессию.
        """
        await self.client.aclose()


class AreaSuggestion:
    def __init__(self, name: str, id: str):
        # текстовое название региона и его внутренний идентификатор
        self.name = name
        self.id = id

async def get_area_suggestions(query: str) -> List[AreaSuggestion]:
    """
    Делает запрос к HH API /suggests/areas?text=<query>
    и возвращает список похожих локаций.
    """
    url = "https://api.hh.ru/suggests/areas"
    params = {"text": query}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", [])
    # из каждого элемента берём 'text' (имя) и 'id'
    return [AreaSuggestion(item["text"], item["id"]) for item in items]