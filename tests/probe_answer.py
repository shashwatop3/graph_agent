"""How the stand-in models answer a probe ("on what day will fire first reach F5?").

They are naive on purpose: believe the last thing read about that field, and if nothing was read,
work it out from the earliest fire they know of. That is what makes a false claim still sitting in
a context leak into the answer, while a context that has had it removed does not.
"""

import re

QUESTION = re.compile(r"On what day will fire first reach F(\d+)\?")
CLAIM = r"fire reaches F{field} on day (\d+)"
BURNING = re.compile(
    r"(?:PUBLISHED: field F(\d+) caught fire on day (\d+))|"
    r"(?:fire reaches F(\d+) on day (\d+) +seen directly)"
)


def is_probe(context: str) -> bool:
    return QUESTION.search(context) is not None


def probe_answer(context: str, n_agents: int) -> str:
    target = int(QUESTION.search(context).group(1))
    claimed = re.findall(CLAIM.format(field=target), context)
    if claimed:
        return claimed[-1]
    known = [(int(a or c), int(b or d)) for a, b, c, d in BURNING.findall(context)]
    if not known:
        return "never"
    field, day = min(known, key=lambda k: k[1])
    return str(day + (target - field) % n_agents)
