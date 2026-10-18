#!/bin/sh
# Start the graph, the shared Gmail and Calendar server, then the console. One container, one
# machine.
set -eu

if [ "$(id -u)" = 0 ]; then
    chown groundwork:groundwork /data  # a new volume is mounted as root's
    exec su-exec groundwork env HOME=/home/groundwork sh "$0"
fi

# FalkorDB on this machine only, keeping nothing on disk: a hosted run's graph is dropped with the
# run (service/app.py). Its defaults cut results at 10000 rows and stop a query after 1 s; lifted,
# as in docker-compose.yml.
redis-server --bind 127.0.0.1 --port "$FALKORDB_PORT" --protected-mode yes \
    --save "" --appendonly no --dir /tmp --maxmemory 400mb --maxmemory-policy noeviction \
    --loadmodule /var/lib/falkordb/bin/falkordb.so \
    RESULTSET_SIZE -1 TIMEOUT 0 MAX_QUEUED_QUERIES 200 &
until redis-cli -p "$FALKORDB_PORT" ping >/dev/null 2>&1; do sleep 0.2; done

# workspace-mcp in its mode for several people: it keeps no one's tokens, and each request signs
# in with the person's own Google access token (service/auth.py, frame/presets.shared_google).
# It listens on this machine only, and gets neither our PORT (it reads PORT before its own) nor
# SECRET_KEY.
env -u PORT -u SECRET_KEY \
    MCP_ENABLE_OAUTH21=true EXTERNAL_OAUTH21_PROVIDER=true WORKSPACE_MCP_STATELESS_MODE=true \
    WORKSPACE_MCP_HOST=127.0.0.1 WORKSPACE_MCP_PORT=8000 \
    workspace-mcp --transport streamable-http --tools gmail calendar --tool-tier core --read-only &

exec /app/.venv/bin/python -m graph_agent.service --host 0.0.0.0 --port "${PORT:-8080}"
