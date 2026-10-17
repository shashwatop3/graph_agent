"""Who is asking: the person at this machine (local), or someone signed in with Google (hosted).

Local is the default and works as before: one person, no sign-in, their files in the repository
and their secrets in .env. Setting GRAPH_AGENT_PUBLIC_URL (the address people open, e.g.
https://cascade.fly.dev) switches to hosted: every API call needs a signed-in person, and each
person has a folder of their own under GRAPH_AGENT_DATA:

    users/<google id>/user.json        their address and name
    users/<google id>/secrets.json     their keys (Anthropic, Todoist, ...), encrypted
    users/<google id>/connections.json, my-teams/, runs/cache/   their apps, teams, model cache

A session is a cookie holding the person's id, when it ends, and a signature made with
SECRET_KEY, so it cannot be made or changed without that key. Nothing is kept server side for it.
A person's keys are encrypted with another key made from SECRET_KEY (Fernet: AES with a MAC), and
are only ever decrypted to run their own things; the API never sends a value back.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from .spaces import ROOT

COOKIE = "cascade_session"
SESSION_DAYS = 30
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # Google's account ids are digits


@dataclass(frozen=True)
class User:
    id: str  # "local", or the Google account's id ("sub")
    email: str
    name: str
    folder: Path  # where their own files live (the repository, for "local")


LOCAL = User("local", "", "", ROOT)


# ---- the mode -----------------------------------------------------------------------------------


def public_url() -> str:
    """The hosted address ("" when local), without a trailing slash."""
    return os.environ.get("GRAPH_AGENT_PUBLIC_URL", "").rstrip("/")


def hosted() -> bool:
    return bool(public_url())


def public_origin() -> str:
    """The origin a hosted page's requests carry ("https://cascade.fly.dev")."""
    url = urlparse(public_url())
    return f"{url.scheme}://{url.netloc}"


def data_dir() -> Path:
    return Path(os.environ.get("GRAPH_AGENT_DATA", "/data"))


def secret_key() -> bytes:
    key = os.environ.get("SECRET_KEY", "")
    if len(key) < 32:
        raise RuntimeError("hosted mode needs SECRET_KEY, of 32 characters or more")
    return key.encode()


def derived_key(purpose: str) -> bytes:
    """A key for one purpose (signing sessions, encrypting secrets), made from SECRET_KEY, so one
    secret is configured and no two uses share a key."""
    return hashlib.sha256(purpose.encode() + b":" + secret_key()).digest()


# ---- people --------------------------------------------------------------------------------------


def folder_of(user_id: str) -> Path:
    if not _ID.fullmatch(user_id):
        raise ValueError(f"not an account id: {user_id!r}")
    return data_dir() / "users" / user_id


def remember(user_id: str, email: str, name: str) -> User:
    """Keep (or update) a person who signed in."""
    folder = folder_of(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "user.json").write_text(json.dumps({"email": email, "name": name}, indent=2) + "\n")
    return User(user_id, email, name, folder)


def load_user(user_id: str) -> User | None:
    try:
        file = folder_of(user_id) / "user.json"
    except ValueError:
        return None
    if not file.exists():
        return None
    data = json.loads(file.read_text())
    return User(user_id, str(data.get("email", "")), str(data.get("name", "")), file.parent)


# ---- sessions ------------------------------------------------------------------------------------


def _sign(text: str) -> str:
    return hmac.new(derived_key("session"), text.encode(), hashlib.sha256).hexdigest()


def session_cookie(user_id: str, now: float | None = None) -> str:
    """The cookie's value for a person who just signed in: "<id>.<ends>.<signature>"."""
    ends = int((now or time.time()) + SESSION_DAYS * 86400)
    text = f"{user_id}.{ends}"
    return f"{text}.{_sign(text)}"


def from_cookie(value: str | None, now: float | None = None) -> User | None:
    """The person a session cookie names, if its signature holds and it has not ended."""
    if not value or value.count(".") != 2:
        return None
    user_id, ends, signature = value.split(".")
    if not hmac.compare_digest(signature, _sign(f"{user_id}.{ends}")):
        return None
    if not ends.isdigit() or int(ends) < (now or time.time()):
        return None
    return load_user(user_id)


# ---- their keys ----------------------------------------------------------------------------------

NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")  # as a connection names it: "$TODOIST_API_KEY"
MAX_SECRETS = 30


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(derived_key("secrets")))


def _secrets_file(user: User) -> Path:
    return user.folder / "secrets.json"


def _stored(user: User) -> dict[str, str]:
    file = _secrets_file(user)
    return json.loads(file.read_text()) if file.exists() else {}


def secret_names(user: User) -> list[str]:
    return sorted(_stored(user))


def save_secret(user: User, name: str, value: str) -> None:
    if not NAME.fullmatch(name):
        raise ValueError(f"{name!r}: a key's name is capitals, digits and _ (TODOIST_API_KEY)")
    value = value.strip()
    if not value or len(value) > 4096:
        raise ValueError("give the key's value (at most 4096 characters)")
    stored = _stored(user)
    if name not in stored and len(stored) >= MAX_SECRETS:
        raise ValueError(f"at most {MAX_SECRETS} keys")
    stored[name] = _fernet().encrypt(value.encode()).decode()
    _write(user, stored)


def delete_secret(user: User, name: str) -> None:
    stored = _stored(user)
    if stored.pop(name, None) is not None:
        _write(user, stored)


def _write(user: User, stored: dict[str, str]) -> None:
    file = _secrets_file(user)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(stored, indent=2) + "\n")
    file.chmod(0o600)


def secrets_of(user: User) -> dict[str, str]:
    """A person's keys, decrypted, plus USER_GOOGLE_EMAIL: the address they signed in with. A key
    that no longer decrypts (SECRET_KEY was changed) is left out, so it shows as not set."""
    found = {"USER_GOOGLE_EMAIL": user.email}
    for name, token in _stored(user).items():
        try:
            found[name] = _fernet().decrypt(token.encode()).decode()
        except InvalidToken:
            continue
    return found
