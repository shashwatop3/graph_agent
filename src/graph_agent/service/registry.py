"""The packs the console offers. To add one, implement `frame.console.ConsolePack` and list it."""

from graph_agent.frame.console import ConsolePack
from graph_agent.packs.hualien.console import HUALIEN
from graph_agent.packs.life.console import LIFE
from graph_agent.packs.offsite.console import OFFSITE
from graph_agent.packs.ringfire.console import RINGFIRE

PACKS: dict[str, ConsolePack] = {pack.name: pack for pack in (LIFE, OFFSITE, RINGFIRE, HUALIEN)}


def pack_named(name: str) -> ConsolePack:
    try:
        return PACKS[name]
    except KeyError:
        raise ValueError(f"unknown pack {name!r}; the packs are {', '.join(PACKS)}") from None
