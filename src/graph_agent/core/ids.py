"""Hands out readable ids (O1, O2, B1, ...) for nodes created while a game runs."""


class Ids:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}{self._counts[prefix]}"
