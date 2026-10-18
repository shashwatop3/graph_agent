"""Signing in with Google, for a hosted console (users.py says what hosted means).

    GET  /auth/login      to Google's sign-in page, and back to /auth/callback
    GET  /auth/callback   Google's answer: the person is kept and gets a session cookie
    POST /auth/logout     ends the session (the cookie is cleared)
    GET  /api/me          {hosted, user}: whether to show the sign-in page, and who is signed in
    GET  /auth/google     a signed-in person connects their Gmail and Calendar (read-only)
    POST /api/google/disconnect   Google's access is revoked and forgotten

Sign-in asks Google only who the person is (openid, email, profile). It uses a Google OAuth client
of type "Web application" whose redirect URI is <public url>/auth/callback; its id and secret are
read from the same names as the Gmail preset's (GOOGLE_OAUTH_CLIENT_ID or GOOGLE_CLIENT_API, and
GOOGLE_OAUTH_CLIENT_SECRET or GOOGLE_CLIENT_SECRET).

Connecting Gmail and Calendar is a second consent, asked only of those who want it: the read-only
scopes, with offline access. Google's refresh token is kept as one of the person's keys
(GOOGLE_REFRESH_TOKEN, encrypted, never handed to an app); `keys_for` makes a short-lived access
token from it (GOOGLE_ACCESS_TOKEN), which the google preset sends to the shared workspace-mcp.

`guard` runs before every request: when hosted, an API call without a valid session gets 401, and
one that changes something must come from the console's own page (its Origin).
"""

import os
import secrets
import time
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from ..frame.connections import resolve
from ..frame.presets import PRESETS, shared_google
from .users import (
    COOKIE,
    LOCAL,
    SESSION_DAYS,
    User,
    delete_secret,
    from_cookie,
    hosted,
    public_origin,
    public_url,
    remember,
    save_secret,
    secrets_of,
    session_cookie,
)

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE = "https://oauth2.googleapis.com/revoke"
STATE = "groundwork_signin"  # the cookie tying Google's answer to the sign-in this browser began
OPEN = {"/api/me"}  # API paths whose GET needs no session
SIGN_IN = "openid email profile"
READ = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
)
REFRESH = "GOOGLE_REFRESH_TOKEN"  # one of the person's keys, kept like the others
ACCESS = "GOOGLE_ACCESS_TOKEN"  # what the google preset sends; made from REFRESH when needed
RESERVED = {REFRESH, ACCESS, "USER_GOOGLE_EMAIL"}  # keys a person cannot set by hand
_access: dict[str, tuple[str, float]] = {}  # person id -> (access token, when it ends)


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


def refresh_access(refresh_token: str) -> tuple[str, float] | None:
    """A new access token and when it ends, or None when Google refuses (access was revoked)."""
    client_id, client_secret = client()
    answer = httpx.post(
        TOKEN,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if answer.status_code != 200:
        return None
    data = answer.json()
    return str(data["access_token"]), time.time() + int(data.get("expires_in", 3600))


def keys_for(user: User) -> dict[str, str]:
    """What a person's apps look their $NAMES up in: their keys, and an access token to their
    Google account if they connected it (one that lasts at least half an hour more, so a run
    started now keeps it). The refresh token itself is never handed out."""
    keys = secrets_of(user)
    refresh = keys.pop(REFRESH, "")
    if not refresh:
        return keys
    held = _access.get(user.id)
    if held is None or held[1] - time.time() < 1800:
        held = refresh_access(refresh)
        if held is None:
            _access.pop(user.id, None)
            return keys  # shows as not connected: they connect again
        _access[user.id] = held
    return {**keys, ACCESS: held[0]}


def hosted_presets() -> dict[str, dict[str, Any]]:
    """The presets of a hosted console: Google through the one workspace-mcp running beside it
    (WORKSPACE_MCP_URL), each request with the person's own token."""
    url = os.environ.get("WORKSPACE_MCP_URL", "http://127.0.0.1:8000/mcp")
    return {**PRESETS, "google": shared_google(url)}


def forget_google(user: User) -> None:
    """Revoke the person's Google access (Google forgets it too) and drop it here."""
    refresh = secrets_of(user).get(REFRESH)
    if refresh:
        httpx.post(REVOKE, data={"token": refresh}, timeout=20)
    delete_secret(user, REFRESH)
    _access.pop(user.id, None)


def google_connected(user: User) -> bool:
    return REFRESH in secrets_of(user)


def guard(request: Request) -> None:
    """Hosted only: who is asking (kept on the request for `current_user`), refusing an API call
    from no one, and a change from another site."""
    if not hosted():
        return
    path = request.url.path
    if not path.startswith("/api/") or (path in OPEN and request.method == "GET"):
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

    def to_google(purpose: str, **asked: str) -> RedirectResponse:
        """To Google's consent page; its answer comes back to /auth/callback with `state`, which
        says what it was for and must match this browser's cookie."""
        if not hosted():
            raise HTTPException(404, "the local console has no sign-in")
        state = f"{purpose}.{secrets.token_urlsafe(24)}"
        query = {
            "client_id": client()[0],
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "state": state,
            **asked,
        }
        response = RedirectResponse(f"{AUTHORIZE}?{urlencode(query)}", status_code=303)
        _cookie(response, STATE, state, max_age=600, path="/auth")
        return response

    @api.get("/auth/login")
    def login() -> RedirectResponse:
        return to_google("signin", scope=SIGN_IN, prompt="select_account")

    @api.get("/auth/google")
    def connect_google(request: Request) -> RedirectResponse:
        user = from_cookie(request.cookies.get(COOKIE)) if hosted() else None
        if user is None:
            return RedirectResponse("/", status_code=303)
        return to_google(
            "google",
            scope=" ".join([SIGN_IN, *READ]),
            access_type="offline",  # a refresh token, so runs can read later without you
            prompt="consent",  # Google gives a refresh token only with a fresh consent
            login_hint=user.email,
        )

    @api.get("/auth/callback")
    def callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
        if not hosted():
            raise HTTPException(404, "the local console has no sign-in")
        if error:
            raise HTTPException(400, f"Google said: {error}")
        expected = request.cookies.get(STATE)
        if not code or not expected or not secrets.compare_digest(state, expected):
            raise HTTPException(400, "this sign-in was not started here; try again")
        tokens = exchange(code)
        who = userinfo(str(tokens["access_token"]))
        if state.startswith("google."):
            return connected(request, tokens, who)
        if not who.get("email_verified"):
            raise HTTPException(403, "Google has not verified this account's address")
        user = remember(str(who["sub"]), str(who["email"]), str(who.get("name", "")))
        response = RedirectResponse("/", status_code=303)
        _cookie(response, COOKIE, session_cookie(user.id), max_age=SESSION_DAYS * 86400)
        response.delete_cookie(STATE, path="/auth")
        return response

    def connected(request: Request, tokens: dict[str, Any], who: dict[str, Any]) -> Response:
        """Google's answer to connecting Gmail and Calendar: keep the refresh token."""
        user = from_cookie(request.cookies.get(COOKIE))
        if user is None:
            raise HTTPException(401, "sign in first")
        if str(who.get("sub")) != user.id:
            raise HTTPException(400, f"connect the account you signed in with ({user.email})")
        granted = set(str(tokens.get("scope", "")).split())
        if not set(READ) <= granted:
            raise HTTPException(400, "Gmail and Calendar need both boxes ticked; try again")
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise HTTPException(400, "Google gave no lasting access; try again")
        save_secret(user, REFRESH, str(refresh))
        ends = time.time() + int(tokens.get("expires_in", 3600))
        _access[user.id] = (str(tokens["access_token"]), ends)
        response = RedirectResponse("/#settings", status_code=303)  # where Connect is
        response.delete_cookie(STATE, path="/auth")
        return response

    @api.post("/api/google/disconnect")
    def disconnect(request: Request) -> dict[str, bool]:
        if not hosted():
            raise HTTPException(404, "the local console connects Google through .env")
        forget_google(current_user(request))
        return {"google": False}

    @api.post("/auth/logout")
    def logout() -> Response:
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/")
        return response

    return api
