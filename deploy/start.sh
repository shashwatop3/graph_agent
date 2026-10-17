#!/bin/sh
# Start the shared Gmail and Calendar server, then the console. One container, one machine.
set -eu

if [ "$(id -u)" = 0 ]; then
    chown cascade:cascade /data  # a new volume is mounted as root's
    exec setpriv --reuid=cascade --regid=cascade --init-groups env HOME=/home/cascade sh "$0"
fi

# workspace-mcp in its mode for several people: it keeps no one's tokens, and each request signs
# in with the person's own Google access token (service/auth.py, frame/presets.shared_google).
# It listens on this machine only, and gets neither our PORT (it reads PORT before its own) nor
# SECRET_KEY.
env -u PORT -u SECRET_KEY \
    MCP_ENABLE_OAUTH21=true EXTERNAL_OAUTH21_PROVIDER=true WORKSPACE_MCP_STATELESS_MODE=true \
    WORKSPACE_MCP_HOST=127.0.0.1 WORKSPACE_MCP_PORT=8000 \
    workspace-mcp --transport streamable-http --tools gmail calendar --tool-tier core --read-only &

exec /app/.venv/bin/python -m graph_agent.service --host 0.0.0.0 --port "${PORT:-8080}"
