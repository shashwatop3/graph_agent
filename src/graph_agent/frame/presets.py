"""Ready-made connections: `{"preset": "google"}` in a connections file is all it takes.

Each is a ready-made MCP server, not a connector of ours: the server does the sign-in, the scopes
and the API calls. A preset says how to start it, which secrets it needs (by their .env names),
which tools to offer and which of them to poll for news. Any field can be changed in the file
(`{"preset": "todoist", "include": ["find-*"]}`).
"""

from typing import Any

GOOGLE_READ = ["search_gmail_messages", "get_gmail_message_content", "get_events", "list_calendars"]
TODOIST_READ = ["find-tasks", "find-tasks-by-date", "find-completed-tasks", "find-projects"]
TODOIST_WRITE = ["add-tasks", "update-tasks", "complete-tasks", "reschedule-tasks"]
# newsletters and promotions are not what a team is for (and cost tokens to read)
SKIP = "-category:promotions -category:social -category:forums"

PRESETS: dict[str, dict[str, Any]] = {
    "google": {
        "label": "Gmail and Calendar (read-only)",
        "about": (
            "workspace-mcp, started read-only: it asks Google for read-only scopes. Needs a "
            "Google OAuth client (Desktop app) and your address; the first run prints a sign-in "
            "link."
        ),
        "command": "uvx",
        "args": [
            "workspace-mcp",
            *("--tools", "gmail", "calendar", "--tool-tier", "core", "--read-only"),
        ],
        "env": {
            "GOOGLE_OAUTH_CLIENT_ID": "$GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET": "$GOOGLE_OAUTH_CLIENT_SECRET",
            "WORKSPACE_MCP_DISABLE_LOCAL_FILES": "true",
        },
        "bind": {"user_google_email": "$USER_GOOGLE_EMAIL"},
        "include": GOOGLE_READ,
        "feeds": [
            {
                "name": "mail",
                "tool": "search_gmail_messages",
                "args": {"query": f"newer_than:7d {SKIP}", "page_size": 10},
                "ids": r"Message ID:\s*([\w-]+)",
                "open": "get_gmail_message_content",
                "open_arg": "message_id",
                "sender": "From",
                "me": "$USER_GOOGLE_EMAIL",
                "sign_in": "authentication",
            },
            {
                "name": "calendar",
                "tool": "get_events",
                "args": {
                    "calendar_id": "primary",
                    "time_min": "{today-1}",
                    "time_max": "{today+30}",
                    "max_results": 50,
                },
                "trusted": True,
                "sign_in": "authentication",
                "limit": 8000,
            },
        ],
    },
    "todoist": {
        "label": "Todoist",
        "about": "The official Todoist server. Needs a personal API token (from Integrations).",
        "command": "npx",
        "args": ["-y", "@doist/todoist-mcp"],
        "env": {"TODOIST_API_KEY": "$TODOIST_API_KEY"},
        "include": [*TODOIST_READ, *TODOIST_WRITE],
        "outward": {name: True for name in TODOIST_WRITE},
    },
}
