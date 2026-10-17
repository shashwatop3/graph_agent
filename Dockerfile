# The hosted console: the service, the built page, and the shared Gmail and Calendar server
# (workspace-mcp), in one container with a volume at /data. See README "Deploying".

# ---- the page ------------------------------------------------------------------------------------
FROM node:22.12.0-bookworm-slim AS page
WORKDIR /page
COPY viewer/console/package.json viewer/console/package-lock.json ./
RUN npm ci
COPY viewer/console/ ./
RUN npm run build

# ---- the service ---------------------------------------------------------------------------------
# Node stays in the image: the Todoist preset starts `npx @doist/todoist-mcp` for a run.
FROM node:22.12.0-bookworm-slim
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
# give a fresh volume (mounted as root's) to the plain user it then runs as.
RUN useradd --create-home cascade && mkdir -p /data
ENV GRAPH_AGENT_DATA=/data NPM_CONFIG_CACHE=/data/npm PORT=8080
EXPOSE 8080
CMD ["sh", "deploy/start.sh"]
