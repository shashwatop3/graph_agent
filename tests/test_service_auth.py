"""A hosted console: people sign in with Google, and nothing is reachable before they do."""

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from graph_agent.service import auth, users  # noqa: E402
from graph_agent.service.app import create_app  # noqa: E402

PUBLIC = "https://cascade.example"


@pytest.fixture
def hosted(tmp_path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001, ANN201
    monkeypatch.setenv("GRAPH_AGENT_PUBLIC_URL", PUBLIC)
    monkeypatch.setenv("GRAPH_AGENT_DATA", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    return tmp_path


def page(**headers: str) -> TestClient:
    return TestClient(create_app(), base_url=PUBLIC, headers={"origin": PUBLIC, **headers})


def signed_in(user_id: str = "1001") -> TestClient:
    users.remember(user_id, f"{user_id}@example.com", "Someone")
    client = page()
    client.cookies.set(users.COOKIE, users.session_cookie(user_id))
    return client


def test_the_local_console_needs_no_sign_in():
    client = TestClient(create_app(), base_url="http://127.0.0.1:8765")
    assert client.get("/api/me").json() == {"hosted": False, "user": None}
    assert client.get("/api/packs").status_code == 200
    assert client.get("/auth/login").status_code == 404


def test_hosted_nothing_is_reachable_before_signing_in(hosted):  # noqa: ANN001
    client = page()
    assert client.get("/api/me").json() == {"hosted": True, "user": None}
    for path in ("/api/packs", "/api/spaces", "/api/connections", "/api/templates"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/spaces", json={}).status_code == 401


def test_a_session_lets_you_in_until_it_ends_or_is_changed(hosted):  # noqa: ANN001
    client = signed_in()
    assert client.get("/api/me").json()["user"] == {"email": "1001@example.com", "name": "Someone"}
    assert client.get("/api/packs").status_code == 200
    value = users.session_cookie("1001")
    user_id, ends, signature = value.split(".")
    for forged in (f"1002.{ends}.{signature}", f"{user_id}.{int(ends) + 1}.{signature}", "x"):
        client.cookies.set(users.COOKIE, forged)
        assert client.get("/api/packs").status_code == 401, forged
    assert users.from_cookie(value, now=float(ends) + 1) is None  # it has ended


def test_hosted_changes_must_come_from_the_console_itself(hosted):  # noqa: ANN001
    client = signed_in()
    other = {"origin": "https://elsewhere.example"}
    assert client.post("/api/validate", json={}, headers=other).status_code == 403
    assert client.post("/api/validate", json={}).status_code == 200


def test_signing_in_with_google(hosted, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001
    client = page()
    start = client.get("/auth/login", follow_redirects=False)
    assert start.status_code == 303
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert query["redirect_uri"] == [f"{PUBLIC}/auth/callback"]
    assert query["scope"] == ["openid email profile"]  # who you are, nothing of your mail
    state = query["state"][0]

    asked: list[str] = []

    def exchange(code: str) -> dict[str, Any]:
        asked.append(code)
        return {"access_token": "token"}

    monkeypatch.setattr(auth, "exchange", exchange)
    monkeypatch.setattr(
        auth,
        "userinfo",
        lambda token: {"sub": "42", "email": "a@example.com", "email_verified": True, "name": "A"},
    )
    wrong = client.get("/auth/callback?code=c&state=other", follow_redirects=False)
    assert wrong.status_code == 400 and not asked  # not the sign-in this browser began
    done = client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False)
    assert done.status_code == 303 and asked == ["c"]
    assert (hosted / "users" / "42" / "user.json").exists()
    assert client.get("/api/me").json()["user"]["email"] == "a@example.com"
    client.post("/auth/logout")
    assert client.get("/api/packs").status_code == 401


def test_no_hosted_console_without_a_secret_key(hosted, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001
    monkeypatch.setenv("SECRET_KEY", "short")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()
