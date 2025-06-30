# hh_api.py
import urllib.parse
import httpx


class HHClient:
    # ── константы ───────────────────────────────────────────────────────
    BASE       = "https://api.hh.ru"
    AUTH_URL   = "https://hh.ru/oauth/authorize"   # всегда hh.ru
    TOKEN_URL  = "https://hh.ru/oauth/token"
    UA         = "AutoReplyBot/1.0 (valshikegor173@gmail.com)"  # ← ваш e-mail

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.redirect_uri  = redirect_uri

    # ────────────────────────────────────────────────────────────────────
    #  OAuth
    # ────────────────────────────────────────────────────────────────────
    async def exchange_code(self, code: str) -> dict:
        """
        Обмен «code → access / refresh».  HH иногда требует непустых UA-заголовков,
        иначе возвращает 403 (DDoS-Guard). Добавляем сразу оба.
        """
        payload = urllib.parse.urlencode({
            "grant_type":    "authorization_code",
            "code":          code,
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri":  self.redirect_uri,
        })

        headers = {
            "User-Agent":     self.UA,          # обычный UA
            "HH-User-Agent":  self.UA,          # HH-специфический
            "Accept":         "application/json",
            "Content-Type":   "application/x-www-form-urlencoded",
        }

        async with httpx.AsyncClient() as c:
            r = await c.post(self.TOKEN_URL, content=payload,
                             headers=headers, timeout=10)

        # ↓ добавь временный лог
        if r.status_code != 200:
            print('HH body:', r.text)  # <— покажет точное описание ошибки

        r.raise_for_status()
        return r.json()

    def get_authorize_url(self) -> str:
        """
        Ссылка, куда отправляем пользователя.
        """
        params = {
            "response_type": "code",
            "client_id":     self.client_id,
            "redirect_uri":  self.redirect_uri,
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    # ────────────────────────────────────────────────────────────────────
    #  Работа с вакансиями / резюме / откликами
    # ────────────────────────────────────────────────────────────────────
    async def _auth_headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "User-Agent":    self.UA,
            "HH-User-Agent": self.UA,
            "Accept":        "application/json",
        }

    async def search_vacancies(
        self,
        access_token: str,
        page: int = 0,
        per_page: int = 10,
        **filters
    ) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.BASE}/vacancies",
                headers=await self._auth_headers(access_token),
                params={"page": page, "per_page": per_page, **filters},
                timeout=10,
            )
            r.raise_for_status()
            return r.json().get("items", [])

    async def respond_to_vacancy(
        self,
        access_token: str,
        resume_id: str,
        vacancy_id: str,
        message: str,
    ) -> int:
        async with httpx.AsyncClient() as c:
            r = await c.post(
                f"{self.BASE}/negotiations",
                headers=await self._auth_headers(access_token),
                data={
                    "vacancy_id": vacancy_id,
                    "resume_id":  resume_id,
                    "message":    message,
                },
                timeout=10,
            )
            r.raise_for_status()
            return r.status_code        # 201 — ok

    async def get_my_resumes(self, access_token: str) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.BASE}/resumes/mine",
                headers=await self._auth_headers(access_token),
                timeout=10,
            )
            r.raise_for_status()
            return r.json().get("items", [])

    async def get_vacancy(self, vacancy_id: str, access_token: str) -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.BASE}/vacancies/{vacancy_id}",
                headers=await self._auth_headers(access_token),
                timeout=10,
            )
            r.raise_for_status()
            return r.json()