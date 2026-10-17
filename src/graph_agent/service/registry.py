"""The packs the console offers. To add one, implement `frame.console.ConsolePack` and list it."""

from pathlib import Path

from graph_agent.frame.console import ConsolePack
from graph_agent.packs.apps.console import APPS, AppsConsole
from graph_agent.packs.hualien.console import HUALIEN
from graph_agent.packs.life.console import LIFE, LifeConsole
from graph_agent.packs.offsite.console import OFFSITE
from graph_agent.packs.ringfire.console import RINGFIRE

from .auth import hosted_presets, keys_for
from .users import LOCAL, User

PACKS: dict[str, ConsolePack] = {
    pack.name: pack for pack in (LIFE, OFFSITE, RINGFIRE, HUALIEN, APPS)
}
_yours: dict[Path, dict[str, ConsolePack]] = {}  # a hosted person's folder -> their packs


def packs_for(user: User = LOCAL) -> dict[str, ConsolePack]:
    """The packs one person sees. Local: these, as they are. Hosted: their own apps and teams
    (files in their folder), and the life pack without the real mailbox (this server's .env)."""
    if user.id == LOCAL.id:
        return PACKS
    if user.folder not in _yours:
        apps = AppsConsole(
            user.folder / "my-teams",
            user.folder / "connections.json",
            lambda: keys_for(user),
            hosted_presets(),
        )
        _yours[user.folder] = {**PACKS, "life": LifeConsole(real=False), "apps": apps}
    return _yours[user.folder]


def forget_packs(user: User) -> None:
    """Drop a person's packs (their account is being deleted)."""
    _yours.pop(user.folder, None)


def pack_named(name: str, user: User = LOCAL) -> ConsolePack:
    packs = packs_for(user)
    try:
        return packs[name]
    except KeyError:
        raise ValueError(f"unknown pack {name!r}; the packs are {', '.join(packs)}") from None
