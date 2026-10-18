# The hosted console: the service, the built page, the shared Gmail and Calendar server
# (workspace-mcp) and the graph (FalkorDB), in one container with a volume at /data. See README
# "Deploying".

# ---- the page ------------------------------------------------------------------------------------
FROM node:22.12.0-bookworm-slim AS page
WORKDIR /page
COPY viewer/console/package.json viewer/console/package-lock.json ./
RUN npm ci
COPY viewer/console/ ./
RUN npm run build

# ---- the service ---------------------------------------------------------------------------------
# Built on the FalkorDB image the tests run against (docker-compose.yml): its redis-server and graph
# module, on this machine only. Node 22 replaces the image's own (kept for its browser, removed):
# the Todoist preset starts `npx @doist/todoist-mcp` for a run.
FROM node:22.12.0-bookworm-slim AS node
FROM falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6
RUN rm -rf /var/lib/falkordb/browser /usr/local/bin/node
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /usr/local/bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app

# workspace-mcp, pinned (its multi-person mode is what presets.shared_google relies on)
RUN uv tool install --python 3.12 workspace-mcp==2.1.0

COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --extra service --no-install-project
COPY src/ src/
RUN uv sync --frozen --no-dev --extra service
COPY --from=page /page/dist viewer/console/dist
COPY deploy/start.sh deploy/start.sh

# /data (the volume) holds everyone's folders and the npm cache. start.sh starts as root only to
# give a fresh volume (mounted as root's) to the plain user it then runs as. The image has no
# useradd, so the user is written in by hand.
RUN echo 'groundwork:x:1000:1000::/home/groundwork:/bin/sh' >> /etc/passwd \
    && echo 'groundwork:x:1000:' >> /etc/group \
    && mkdir -p /data /home/groundwork && chown groundwork:groundwork /home/groundwork
ENV GRAPH_AGENT_DATA=/data NPM_CONFIG_CACHE=/data/npm PORT=8080 \
    FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=16379
EXPOSE 8080
ENTRYPOINT []
CMD ["sh", "deploy/start.sh"]
