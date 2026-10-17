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


# ---- D2: each person's own runs, apps and teams -------------------------------------------------


def test_a_run_is_only_seen_and_driven_by_whoever_started_it(hosted):  # noqa: ANN001
    alice, bob = signed_in("1"), signed_in("2")
    life = next(t for t in alice.get("/api/templates").json() if t["pack"] == "life")
    team = alice.get(f"/api/templates/life/{life['name']}").json()
    made = alice.post("/api/spaces", json={"pack": "life", "team": team}).json()
    assert [s["id"] for s in alice.get("/api/spaces").json()] == [made["id"]]
    assert bob.get("/api/spaces").json() == []
    for path in ("", "/events", "/stream"):
        assert bob.get(f"/api/spaces/{made['id']}{path}").status_code == 404, path
    assert bob.post(f"/api/spaces/{made['id']}/step").status_code == 404
    assert bob.delete(f"/api/spaces/{made['id']}").status_code == 404
    assert alice.post(f"/api/spaces/{made['id']}/step").status_code == 200


def test_apps_and_teams_are_kept_in_each_persons_folder(hosted):  # noqa: ANN001
    alice, bob = signed_in("1"), signed_in("2")
    saved = alice.put("/api/connections", json={"connections": [{"preset": "todoist"}]})
    assert saved.status_code == 200
    assert (hosted / "users" / "1" / "connections.json").exists()
    assert bob.get("/api/connections").json()["entries"] == []
    team = {"name": "Uni", "agents": [{"name": "inbox", "job": "Read my mail."}]}
    assert alice.put("/api/packs/apps/setup", json=team).json()["team"] == "uni"
    assert (hosted / "users" / "1" / "my-teams" / "uni.json").exists()
    assert bob.get("/api/packs/apps/setup").json()["teams"] == []
    assert ("apps", "uni") not in {(t["pack"], t["name"]) for t in bob.get("/api/templates").json()}


def test_hosted_has_no_real_mailbox_of_the_server(hosted):  # noqa: ANN001
    client = signed_in()
    names = {(t["pack"], t["name"]) for t in client.get("/api/templates").json()}
    assert ("life", "real") not in names
    assert client.get("/api/templates/life/real").status_code == 404
    life = next(t for t in client.get("/api/templates").json() if t["pack"] == "life")
    team = client.get(f"/api/templates/life/{life['name']}").json()
    team["settings"]["extra"]["real"] = True  # asked for anyway, by a team made by hand
    refused = client.post("/api/spaces", json={"pack": "life", "team": team})
    assert refused.status_code == 400 and "real mailbox" in refused.json()["detail"]


def test_only_recorded_runs_replay_from_the_shared_cache(hosted):  # noqa: ANN001
    client = signed_in()
    asked = client.post("/api/runs/replay", json={"pack": "apps", "name": "uni"})
    assert asked.status_code == 404


# ---- D3: each person's own keys ------------------------------------------------------------------


def test_keys_are_kept_encrypted_per_person_and_never_sent_back(
    hosted,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
):
    alice, bob = signed_in("1"), signed_in("2")
    assert alice.get("/api/keys").json() == {
        "saved": [],
        "wanted": ["ANTHROPIC_API_KEY"],
        "google": False,
    }
    put = alice.put("/api/keys/TODOIST_API_KEY", json={"value": " todo-secret "})
    assert put.json() == {"saved": ["TODOIST_API_KEY"]}
    assert "todo-secret" not in (hosted / "users" / "1" / "secrets.json").read_text()
    assert "todo-secret" not in alice.get("/api/keys").text
    assert bob.get("/api/keys").json()["saved"] == []
    assert users.secrets_of(users.User("1", "", "", hosted / "users" / "1")) == {
        "USER_GOOGLE_EMAIL": "",
        "TODOIST_API_KEY": "todo-secret",
    }
    assert alice.put("/api/keys/bad name", json={"value": "x"}).status_code == 400
    assert alice.put("/api/keys/USER_GOOGLE_EMAIL", json={"value": "x"}).status_code == 400
    assert alice.delete("/api/keys/TODOIST_API_KEY").json() == {"saved": []}
    monkeypatch.delenv("GRAPH_AGENT_PUBLIC_URL")
    local = TestClient(create_app(), base_url="http://127.0.0.1:8765")
    assert local.get("/api/keys").status_code == 404  # locally they are in .env


def test_an_app_looks_its_secrets_up_in_your_keys(hosted, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001
    monkeypatch.setenv("TODOIST_API_KEY", "the-servers-own")  # not anyone else's to use
    client = signed_in()
    client.put("/api/connections", json={"connections": [{"preset": "todoist"}]})
    (todoist,) = client.get("/api/connections").json()["connections"]
    assert todoist["missing"] == ["TODOIST_API_KEY"]
    asked = client.post("/api/connections/test", json={"preset": "todoist"}).json()
    assert asked == {"ok": False, "error": "add TODOIST_API_KEY under Your keys"}
    assert client.get("/api/keys").json()["wanted"] == ["ANTHROPIC_API_KEY", "TODOIST_API_KEY"]
    client.put("/api/keys/TODOIST_API_KEY", json={"value": "mine"})
    (todoist,) = client.get("/api/connections").json()["connections"]
    assert todoist["missing"] == []


def test_hosted_apps_are_presets_or_servers_on_the_internet(hosted):  # noqa: ANN001
    client = signed_in()

    def refused(entry: dict[str, Any]) -> str:
        answer = client.put("/api/connections", json={"connections": [entry]})
        assert answer.status_code == 400, entry
        return answer.json()["detail"]

    assert "not a command" in refused({"name": "x", "command": "rm", "args": ["-rf", "/"]})
    assert "cannot change" in refused({"preset": "todoist", "command": "sh"})
    assert "cannot change" in refused({"preset": "google", "env": {"X": "y"}})
    assert "https://" in refused({"name": "x", "url": "http://1.1.1.1/mcp"})
    for inside in ("https://127.0.0.1/mcp", "https://10.0.0.5/mcp", "https://169.254.169.254/"):
        assert "public internet" in refused({"name": "x", "url": inside})
    ok = {"connections": [{"name": "x", "url": "https://1.1.1.1/mcp"}, {"preset": "todoist"}]}
    assert client.put("/api/connections", json=ok).status_code == 200


def test_a_hosted_run_spends_only_from_your_own_key(hosted, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001
    monkeypatch.setenv("ANTHROPIC_API_KEY", "the-servers-own")
    client = signed_in()
    life = next(t for t in client.get("/api/templates").json() if t["pack"] == "life")
    team = client.get(f"/api/templates/life/{life['name']}").json()
    body = {"pack": "life", "team": team, "model": "claude-haiku-5-5"}
    refused = client.post("/api/spaces", json=body)
    assert refused.status_code == 400 and "Your keys" in refused.json()["detail"]


# ---- D4: Gmail and Calendar through one shared workspace-mcp -------------------------------------

BOTH = " ".join(["openid", *auth.READ])


def connect_google(client: TestClient, monkeypatch: pytest.MonkeyPatch, **answer: Any) -> Any:
    """Go through "Connect Gmail and Calendar", Google answering with `answer` (tokens, who)."""
    start = client.get("/auth/google", follow_redirects=False)
    query = parse_qs(urlparse(start.headers["location"]).query)
    tokens = {"access_token": "a1", "refresh_token": "r1", "scope": BOTH, "expires_in": 3600}
    tokens.update(answer.get("tokens", {}))
    who = {"sub": "1", "email": "1@example.com", "email_verified": True, **answer.get("who", {})}
    monkeypatch.setattr(auth, "exchange", lambda code: tokens)
    monkeypatch.setattr(auth, "userinfo", lambda token: who)
    state = query["state"][0]
    return client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False)


def test_connecting_gmail_asks_google_for_read_only_access(hosted, monkeypatch):  # noqa: ANN001
    client = signed_in("1")
    start = client.get("/auth/google", follow_redirects=False)
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert set(query["scope"][0].split()) == {"openid", "email", "profile", *auth.READ}
    assert query["access_type"] == ["offline"] and query["state"][0].startswith("google.")
    assert page().get("/auth/google", follow_redirects=False).headers["location"] == "/"
    assert connect_google(client, monkeypatch, who={"sub": "2"}).status_code == 400
    narrow = {"scope": "openid " + auth.READ[0]}  # a box left unticked
    assert connect_google(client, monkeypatch, tokens=narrow).status_code == 400
    assert not client.get("/api/keys").json()["google"]
    done = connect_google(client, monkeypatch)
    assert done.status_code == 303 and done.headers["location"] == "/#apps"
    keys = client.get("/api/keys").json()
    assert keys["google"] and keys["saved"] == []  # the refresh token is not a key you see
    assert "r1" not in (hosted / "users" / "1" / "secrets.json").read_text()
    for name in ("GOOGLE_REFRESH_TOKEN", "GOOGLE_ACCESS_TOKEN"):
        assert client.put(f"/api/keys/{name}", json={"value": "x"}).status_code == 400


def test_the_google_preset_reaches_the_shared_server_with_your_token(hosted, monkeypatch):  # noqa: ANN001
    from graph_agent.service.registry import pack_named

    monkeypatch.setenv("WORKSPACE_MCP_URL", "http://127.0.0.1:8000/mcp")
    client = signed_in("1")
    assert client.put("/api/connections", json={"connections": [{"preset": "google"}]}).is_success
    (google,) = client.get("/api/connections").json()["connections"]
    assert google["missing"] == ["GOOGLE_ACCESS_TOKEN"]
    asked = client.post("/api/connections/test", json={"preset": "google"}).json()
    assert asked["error"] == "connect your Google account under Your keys"
    connect_google(client, monkeypatch)
    (google,) = client.get("/api/connections").json()["connections"]
    assert google["missing"] == []
    (connection,) = pack_named("apps", users.load_user("1")).connections()  # type: ignore[attr-defined, arg-type]
    assert connection.command is None and connection.url == "http://127.0.0.1:8000/mcp"
    assert connection.resolve(connection.headers["Authorization"]) == "Bearer a1"
    assert connection.resolve(connection.bind["user_google_email"]) == "1@example.com"


def test_an_access_token_is_made_again_before_it_runs_out(hosted, monkeypatch):  # noqa: ANN001
    user = users.remember("1", "1@example.com", "")
    users.save_secret(user, auth.REFRESH, "r1")
    made: list[str] = []

    def refresh(token: str) -> tuple[str, float] | None:
        made.append(token)
        return (f"a{len(made)}", auth.time.time() + 3600) if len(made) < 3 else None

    monkeypatch.setattr(auth, "refresh_access", refresh)
    auth._access.pop("1", None)  # pyright: ignore[reportPrivateUsage]
    assert auth.keys_for(user)[auth.ACCESS] == "a1"
    assert auth.keys_for(user)[auth.ACCESS] == "a1" and made == ["r1"]  # still fresh
    auth._access["1"] = ("a1", auth.time.time() + 600)  # pyright: ignore[reportPrivateUsage]
    assert auth.keys_for(user)[auth.ACCESS] == "a2"  # ten minutes left is too few for a run
    auth._access["1"] = ("a2", 0)  # pyright: ignore[reportPrivateUsage]
    assert auth.ACCESS not in auth.keys_for(user)  # Google refused: shows as not connected
    assert auth.REFRESH not in auth.keys_for(user)  # never handed to an app


def test_disconnecting_google_revokes_and_forgets_it(hosted, monkeypatch):  # noqa: ANN001
    client = signed_in("1")
    connect_google(client, monkeypatch)
    revoked: list[str] = []
    monkeypatch.setattr(
        auth.httpx, "post", lambda url, data, timeout: revoked.append(data["token"])
    )
    assert client.post("/api/google/disconnect").json() == {"google": False}
    assert revoked == ["r1"] and not client.get("/api/keys").json()["google"]
