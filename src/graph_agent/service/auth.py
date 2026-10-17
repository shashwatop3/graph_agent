"""Signing in with Google, for a hosted console (users.py says what hosted means).

    GET  /auth/login      to Google's sign-in page, and back to /auth/callback
    GET  /auth/callback   Google's answer: the person is kept and gets a session cookie
    POST /auth/logout     ends the session (the cookie is cleared)
    GET  /api/me          {hosted, user}: whether to show the sign-in page, and who is signed in

Sign-in asks Google only who the person is (openid, email, profile). It uses a Google OAuth client
of type "Web application" whose redirect URI is <public url>/auth/callback; its id and secret are
read from the same names as the Gmail preset's (GOOGLE_OAUTH_CLIENT_ID or GOOGLE_CLIENT_API, and
GOOGLE_OAUTH_CLIENT_SECRET or GOOGLE_CLIENT_SECRET).

`guard` runs before every request: when hosted, an API call without a valid session gets 401, and
one that changes something must come from the console's own page (its Origin).
"""

import secrets
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from ..frame.connections import resolve
from .users import (
    COOKIE,
    LOCAL,
    SESSION_DAYS,
    User,
    from_cookie,
    hosted,
    public_origin,
    public_url,
    remember,
    session_cookie,
)

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
STATE = "cascade_signin"  # the cookie that ties Google's answer to the sign-in this browser began
OPEN = {"/api/me"}  # API paths that need no session


def client() -> tuple[str, str]:
    found = (
        resolve("${GOOGLE_OAUTH_CLIENT_ID|GOOGLE_CLIENT_API}"),
        resolve("${GOOGLE_OAUTH_CLIENT_SECRET|GOOGLE_CLIENT_SECRET}"),
    )
    if not all(found):
        raise HTTPException(500, "the server has no Google OAuth client configured")
    return found


def redirect_uri() -> str:
    return f"{public_url()}/auth/callback"


def exchange(code: str) -> dict[str, Any]:
    """Google's tokens for the code it sent back."""
    client_id, client_secret = client()
    answer = httpx.post(
        TOKEN,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if answer.status_code != 200:
        raise HTTPException(400, f"Google refused the sign-in: {answer.text[:200]}")
    return cast(dict[str, Any], answer.json())


def userinfo(access_token: str) -> dict[str, Any]:
    """Who the token belongs to (sub, email, email_verified, name)."""
    answer = httpx.get(USERINFO, headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
    answer.raise_for_status()
    return cast(dict[str, Any], answer.json())


def guard(request: Request) -> None:
    """Hosted only: who is asking (kept on the request for `current_user`), refusing an API call
    from no one, and a change from another site."""
    if not hosted():
        return
    path = request.url.path
    if not path.startswith("/api/") or path in OPEN:
        return
    user = from_cookie(request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "sign in first")
    if request.method not in ("GET", "HEAD") and request.headers.get("origin") != public_origin():
        raise HTTPException(403, "not from this console")
    request.state.user = user


def current_user(request: Request) -> User:
    """The person the request is for: the signed-in one when hosted, else the local one."""
    return cast(User, getattr(request.state, "user", LOCAL)) if hosted() else LOCAL


def _cookie(response: Response, name: str, value: str, max_age: int, path: str = "/") -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=path,
        httponly=True,  # the page's scripts cannot read it
        secure=public_url().startswith("https://"),
        samesite="lax",  # not sent with requests other sites make (only when following a link)
    )


def router() -> APIRouter:
    api = APIRouter()

    @api.get("/api/me")
    def me(request: Request) -> dict[str, Any]:
        if not hosted():
            return {"hosted": False, "user": None}
        user = from_cookie(request.cookies.get(COOKIE))
        return {
            "hosted": True,
            "user": None if user is None else {"email": user.email, "name": user.name},
        }

    @api.get("/auth/login")
    def login() -> RedirectResponse:
        if not hosted():
            raise HTTPException(404, "the local console has no sign-in")
        state = secrets.token_urlsafe(24)
        query = {
            "client_id": client()[0],
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
        response = RedirectResponse(f"{AUTHORIZE}?{urlencode(query)}", status_code=303)
        _cookie(response, STATE, state, max_age=600, path="/auth")
        return response

    @api.get("/auth/callback")
    def callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
        if not hosted():
            raise HTTPException(404, "the local console has no sign-in")
        if error:
            raise HTTPException(400, f"Google said: {error}")
        expected = request.cookies.get(STATE)
        if not code or not expected or not secrets.compare_digest(state, expected):
            raise HTTPException(400, "this sign-in was not started here; try again")
        who = userinfo(str(exchange(code)["access_token"]))
        if not who.get("email_verified"):
            raise HTTPException(403, "Google has not verified this account's address")
        user = remember(str(who["sub"]), str(who["email"]), str(who.get("name", "")))
        response = RedirectResponse("/", status_code=303)
        _cookie(response, COOKIE, session_cookie(user.id), max_age=SESSION_DAYS * 86400)
        response.delete_cookie(STATE, path="/auth")
        return response

    @api.post("/auth/logout")
    def logout() -> Response:
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/")
        return response

    return api
