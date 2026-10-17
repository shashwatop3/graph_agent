"""Start the console: uv run python -m graph_agent.service [--port 8765]."""

import argparse

from .app import main

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()
main(args.host, args.port)
