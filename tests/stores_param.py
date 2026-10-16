"""The list of stores that tests run against, shared so every suite covers all three."""

import pytest

from graph_agent.stores.falkor import FalkorStore
from graph_agent.stores.memory import MemoryStore
from graph_agent.stores.postgres import PostgresStore

# The database-backed ones are marked integration, so `pytest -m "not integration"` skips them.
STORES = [
    pytest.param(MemoryStore, id="memory"),
    pytest.param(FalkorStore, id="falkor", marks=pytest.mark.integration),
    pytest.param(PostgresStore, id="postgres", marks=pytest.mark.integration),
]
