"""Smoke tests: both databases are reachable and behave as expected.

Needs the services from docker-compose.yml:  docker compose up -d --wait
Skip them with:  uv run pytest -m "not integration"
"""

import os

import psycopg
import pytest
from falkordb import FalkorDB

pytestmark = pytest.mark.integration

FALKORDB_HOST = os.environ.get("FALKORDB_HOST", "127.0.0.1")
FALKORDB_PORT = int(os.environ.get("FALKORDB_PORT", "16379"))
POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN", "postgresql://postgres:postgres@127.0.0.1:15432/graph_agent"
)


def test_falkordb_runs_a_cypher_query():
    db = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT)
    graph = db.select_graph("s0_smoke")
    try:
        graph.query("CREATE (:A {id: 1})-[:R]->(:B {id: 2})")
        result = graph.query("MATCH (a:A)-[:R]->(b:B) RETURN a.id, b.id")
        assert result.result_set == [[1, 2]]
    finally:
        graph.delete()


def test_falkordb_has_the_graph_module():
    db = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT)
    modules = db.connection.execute_command("MODULE", "LIST")
    names = {m[1].decode() if isinstance(m[1], bytes) else m[1] for m in modules}
    assert "graph" in names


@pytest.mark.postgres
def test_postgres_runs_a_recursive_query():
    with psycopg.connect(POSTGRES_DSN) as conn:
        rows = conn.execute(
            "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 5) "
            "SELECT sum(i) FROM n"
        ).fetchall()
        assert rows == [(15,)]
        major = conn.execute("SHOW server_version_num").fetchone()[0]
        assert int(major) >= 170000


def test_falkordb_does_not_silently_cut_results_or_kill_slow_queries():
    """FalkorDB's defaults return at most 10000 rows without any error and abort queries that run
    longer than 1 second. Either would quietly corrupt benchmark answers, so docker-compose.yml
    lifts both (FALKORDB_ARGS). If this fails, recreate the container: docker compose up -d
    --force-recreate falkordb
    """
    db = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT)
    graph = db.select_graph("s6_limits")
    try:
        assert len(graph.query("UNWIND range(1, 25000) AS i RETURN i").result_set) == 25000
        assert db.connection.execute_command("GRAPH.CONFIG", "GET", "TIMEOUT")[1] == 0
    finally:
        try:
            graph.delete()
        except Exception:
            pass
