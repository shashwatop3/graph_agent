from graph_agent.stores.memory import MemoryStore
from store_contract import StoreContract


class TestMemoryStore(StoreContract):
    def make_store(self):
        return MemoryStore()
