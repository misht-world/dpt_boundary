# -*- coding: utf-8 -*-
"""Простой вход по одному паролю (для публикации в интернет).

Включается только если задана переменная окружения APP_PASSWORD.
Пусто — вход выключен, приложение работает как на ПK (run.bat).

- cookie-сессия на itsdangerous, срок ~72 ч;
- без входа закрыты все страницы и /api/* (кроме самой страницы входа);
- лимит неверных попыток с одного IP за 15 минут;
- IP берётся из заголовка X-Forwarded-For (перед приложением прокси).
"""
import os
import pathlib
import secrets
import time
from collections import defaultdict

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "boundary_session"
SESSION_HOURS = 72
MAX_ATTEMPTS = 10
WINDOW_SECONDS = 900  # 15 минут

PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
ENABLED = bool(PASSWORD)

# Секрет сессии задаётся на сервере (SESSION_SECRET). Если его нет —
# случайный на время работы процесса (сессии не переживут перезапуск,
# для локального запуска это неважно).
_secret = os.environ.get("SESSION_SECRET", "").strip() or secrets.token_urlsafe(32)
_serializer = URLSafeTimedSerializer(_secret, salt="boundary-session")
_max_age = SESSION_HOURS * 3600
_attempts: dict[str, list[float]] = defaultdict(list)

# Пути, доступные без входа.
_PUBLIC = {"/login", "/api/login", "/api/logout"}
_LOGIN_HTML = pathlib.Path(__file__).resolve().parent / "static" / "login.html"


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _throttled(ip: str) -> bool:
    window = time.time() - WINDOW_SECONDS
    tries = [t for t in _attempts[ip] if t > window]
    _attempts[ip] = tries
    return len(tries) >= MAX_ATTEMPTS


def _record_failure(ip: str) -> None:
    _attempts[ip].append(time.time())


def _issue() -> str:
    return _serializer.dumps({"ok": True})


def _valid(token: str | None) -> bool:
    if not token:
        return False
    try:
        _serializer.loads(token, max_age=_max_age)
        return True
    except (BadSignature, SignatureExpired):
        return False


def install(app: FastAPI) -> None:
    """Вешает на приложение страницу входа и, если включено, защиту."""

    @app.get("/login")
    def login_page():
        return FileResponse(_LOGIN_HTML,
                            headers={"Cache-Control": "no-cache"})

    @app.post("/api/login")
    def login(request: Request, password: str = Form(...)):
        ip = _client_ip(request)
        if _throttled(ip):
            raise HTTPException(
                429, "Слишком много попыток. Попробуйте через 15 минут.")
        if not (PASSWORD and secrets.compare_digest(password, PASSWORD)):
            _record_failure(ip)
            raise HTTPException(401, "Неверный пароль")
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE_NAME, _issue(), max_age=_max_age,
                        httponly=True, samesite="lax", secure=False, path="/")
        return resp

    @app.post("/api/logout")
    def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE_NAME, path="/")
        return resp

    if not ENABLED:
        return

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC or _valid(request.cookies.get(COOKIE_NAME)):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Требуется вход"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
