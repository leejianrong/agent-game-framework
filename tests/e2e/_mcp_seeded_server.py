"""Test-only launcher: a stdio MCP server wired exactly like
``agent_game_framework.connectors.mcp.server.main()`` -- two-seat Tic-Tac-Toe,
seat "O" auto-played by ``RandomBotController`` via ``bot_seats``, seat "X"
left for whichever MCP client connects -- except seat "O"'s
``RandomBotController`` is given a *seeded* ``random.Random`` instead of
``main()``'s unseeded one.

Why this exists instead of just spawning ``main()``'s own entry point
(``python -m agent_game_framework.connectors.mcp.server``): KAN-1283's e2e
acceptance criterion needs a reproducible bot opponent so the MCP-driven game
can be compared against an equivalent in-process baseline built from the same
seed (see ``tests/e2e/test_mcp_play.py``'s docstring for the full
reasoning). Neither ``main()`` nor the CLI's ``bot:random`` seat expose a
seed knob -- adding one is out of scope for this MCP-focused ticket (see the
ticket description) -- so the knob lives here instead, in a test-only script
that is never shipped in ``src/`` and never imported by anything except the
e2e test harness that spawns it as a subprocess.

Run as ``python <this file's path> <seed>`` (a positional argv, not an env
var or ``python -m``, since this file lives under ``tests/`` rather than
inside an importable package -- ``python -m`` needs a dotted module path on
``sys.path``, which this deliberately is not). Like the existing CLI e2e
tests (``tests/e2e/test_cli_play.py``), the *subprocess's* ``PYTHONPATH``
must include the repo root for ``examples.tictactoe`` to import (ADR-0001:
it lives outside ``src/``) -- see ``mcp_client_harness.py``'s
``_extra_server_env()`` for where that's set for this script specifically.
"""

from __future__ import annotations

import random
import sys
from typing import Any

from agent_game_framework.agents import RandomBotController
from agent_game_framework.connectors.mcp import build_server
from agent_game_framework.core import Match
from examples.tictactoe import TicTacToeEngine


def main(seed: int) -> None:
    match: Match[Any, Any, Any] = Match(TicTacToeEngine(), players=["X", "O"])
    server = build_server(match, bot_seats={"O": RandomBotController(random.Random(seed))})
    server.run("stdio")


if __name__ == "__main__":
    main(int(sys.argv[1]))
