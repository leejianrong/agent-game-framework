"""Test-only MCP client harness (KAN-1283, SLICES.md V2 step 3, ADR-0006):
connects to an MCP server over a *real* stdio subprocess pipe and plays a
full, scripted Tic-Tac-Toe game as seat "X".

This is deliberately not the in-process ``mcp.Client`` that
``tests/integration/test_mcp_server.py`` uses (see that module's docstring)
-- ``Client`` talks directly to an ``MCPServer`` instance living in the same
process, with no subprocess, no real pipe, and no serialization boundary to
cross. This harness instead uses the MCP SDK's real transport pair,
``mcp.stdio_client`` (spawns the server subprocess, bridges its stdin/stdout
to the session) plus ``mcp.ClientSession`` (the JSON-RPC session on top) --
confirmed by reading ``mcp/client/stdio.py`` and ``mcp/client/session.py``
directly in this installed SDK version, not assumed from the in-process
``Client`` API. The result shape returned by ``ClientSession.call_tool``
(``types.CallToolResult``, with ``.is_error`` and ``.structured_content``) is
the same type ``Client.call_tool`` returns in-process, so the assertions
here read identically to the integration tests' -- only how the session is
established differs.

Seat "X"'s policy here is deliberately trivial and deterministic: always
submit whichever action ``list_legal_actions`` lists first. This mirrors
``test_full_game_completes_via_one_client_with_bot_seat_auto_playing`` in
``tests/integration/test_mcp_server.py`` (KAN-1282), which drives the exact
same policy in-process -- so ``tests/e2e/test_mcp_play.py`` can reproduce
this harness's game with an in-process baseline built from the identical
policy plus the identical seed for seat "O"'s ``RandomBotController``.
Seat "O" itself is never named in a ``submit_action`` call from this
harness (or any client) -- it is entirely auto-played server-side via
``build_server(..., bot_seats=...)`` (KAN-1282), synchronously within each
``submit_action`` tool call, before that call's response is returned. That
is what makes checking "is the game over yet" via ``get_observation("X")``'s
``current_players`` field safe: by the time control returns to this
harness, any pending "O" turns have already resolved, so an empty
``current_players`` unambiguously means the match is terminal, never just
"it's O's turn."
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[2]
_SEEDED_SERVER_SCRIPT = Path(__file__).resolve().with_name("_mcp_seeded_server.py")


def _extra_server_env() -> dict[str, str]:
    """Extra environment variables layered over ``stdio_client``'s own
    default set.

    Unlike ``subprocess.run``, whose ``env=`` argument (as
    ``tests/e2e/test_cli_play.py``'s ``_subprocess_env()`` uses it) replaces
    the *entire* child environment, ``mcp.StdioServerParameters.env`` is
    documented (see ``mcp/client/stdio.py``) as merged *over*
    ``get_default_environment()`` -- a small fixed allowlist (``HOME``,
    ``PATH``, etc. on POSIX), not a copy of this process's full ``os.environ``.
    So this harness does not need to (and should not) reconstruct a full
    environment the way the CLI e2e tests do -- it only needs to add
    ``PYTHONPATH`` so the spawned ``_mcp_seeded_server.py`` subprocess can
    import ``examples.tictactoe`` from outside ``src/`` (ADR-0001), exactly
    the one thing those CLI tests' ``PYTHONPATH`` line is also for.
    """
    existing = os.environ.get("PYTHONPATH")
    pythonpath = str(REPO_ROOT) if not existing else f"{REPO_ROOT}{os.pathsep}{existing}"
    return {"PYTHONPATH": pythonpath}


def _server_params(command: str, seed: int) -> StdioServerParameters:
    return StdioServerParameters(
        command=command,
        args=[str(_SEEDED_SERVER_SCRIPT), str(seed)],
        env=_extra_server_env(),
    )


async def play_full_game_as_seat_x(command: str, seed: int) -> dict[str, Any]:
    """Spawn a seeded MCP server subprocess, play seat "X" to completion,
    and return the final ``get_state_dump`` payload.

    ``command`` is the Python interpreter to spawn ``_mcp_seeded_server.py``
    with -- callers pass ``sys.executable`` so the subprocess runs under the
    same interpreter (and therefore the same installed ``agent_game_framework``
    package) as the test process itself.
    """
    params = _server_params(command, seed)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            while True:
                obs = await session.call_tool("get_observation", {"player": "X"})
                if not obs.structured_content["current_players"]:
                    break  # terminal -- see module docstring for why this is safe to trust

                legal = await session.call_tool("list_legal_actions", {"player": "X"})
                action = legal.structured_content["result"][0]

                result = await session.call_tool(
                    "submit_action", {"player": "X", "action": action}
                )
                assert result.is_error is False, (
                    f"submit_action(X, {action!r}) unexpectedly failed: {result.content!r}"
                )

            state = await session.call_tool("get_state_dump", {})
            final_state: dict[str, Any] = state.structured_content
            return final_state
