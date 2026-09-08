"""Stdio MCP server exposing ``get_observation``/``list_legal_actions``/
``submit_action``/``get_state_dump`` over one ``Match`` instance (ADR-0006,
PLAN.md Shape S6, KAN-1281).

Per ADR-0006, this is a *thin* adapter: each tool below calls exactly one
``Match`` method and relays its result (or, for ``submit_action``, its
``IllegalActionError``) -- no rule-checking or legality validation happens
in this module. ``Match``/``GameEngine.apply_action`` remains the sole
authority on what is legal.

Built on the official MCP Python SDK (PyPI: ``mcp``) using its high-level
``mcp.server.mcpserver.MCPServer`` API (this installed SDK version renamed
the earlier ``FastMCP`` name to ``MCPServer`` -- ``mcp.server.fastmcp`` now
raises ``ModuleNotFoundError`` pointing at the rename). ``@server.tool()``
derives each tool's JSON input schema from the wrapped function's type
hints and validates every call's arguments against it (via a pydantic
model built from the signature) *before* the function body ever runs --
this is what makes a malformed ``submit_action`` payload (wrong type,
missing field) get rejected before it reaches ``Match`` at all, with no
input-validation code of our own to maintain. A validation failure there
surfaces as ``ToolError`` (see ``tools/base.py::Tool.run``), the SDK's own
"deliberate, anticipated tool failure" signal, which the server's request
handler turns into a structured ``CallToolResult(is_error=True, ...)``
instead of a raw crash -- the exact same mechanism ``submit_action`` below
uses to surface ``IllegalActionError`` as a structured tool error.

``action`` on ``submit_action`` is typed plain ``int`` because that is
``TicTacToeEngine``'s concrete ``ActionT`` -- the only game this ticket
needs to serve. A future game with a structured/non-int action type would
need its own tool input shape; that is out of scope here (see the ticket).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from agent_game_framework.core import IllegalActionError, Match, PlayerId

SERVER_NAME = "agent-game-framework"


def build_server(match: Match[Any, Any, Any], *, name: str = SERVER_NAME) -> MCPServer[None]:
    """Build an ``MCPServer`` exposing the four tools over ``match``.

    ``match`` is the one ``Match`` instance every tool call below operates
    against -- callers construct it however they like (which engine, which
    players, whether a seat map is attached) before handing it here; this
    function never constructs a ``Match`` itself. Multiple MCP clients (or
    one client driving every seat itself, a valid way to exercise this
    ticket in isolation -- see the module docstring of the tests) all share
    this same instance, so every tool call sees the same, single, current
    state.
    """
    server: MCPServer[None] = MCPServer(name=name)

    @server.tool()
    def get_observation(player: PlayerId) -> dict[str, Any]:
        """Return ``player``'s current observation of the match."""
        result: dict[str, Any] = match.observation_for(player)
        return result

    @server.tool()
    def list_legal_actions(player: PlayerId) -> list[Any]:
        """Return the actions ``player`` may currently take."""
        return list(match.legal_actions(player))

    @server.tool()
    def submit_action(player: PlayerId, action: int) -> dict[str, Any]:
        """Apply ``action`` on behalf of ``player``.

        On success, returns the new ``match.serialize()`` state so the
        caller can see the result of its own move without a separate
        ``get_state_dump`` round trip. On ``IllegalActionError`` -- an
        illegal move, or a call out of turn -- raises ``ToolError`` so the
        MCP layer reports a structured tool error (``is_error=True``) back
        to the client instead of crashing or silently no-op'ing; per
        ``Match.submit_action``'s own contract, the match's state is left
        completely unchanged in that case.
        """
        try:
            match.submit_action(player, action)
        except IllegalActionError as exc:
            raise ToolError(str(exc)) from exc
        return match.serialize()

    @server.tool()
    def get_state_dump() -> dict[str, Any]:
        """Return the full current match state (``Match.serialize()``)."""
        return match.serialize()

    return server


def main() -> None:
    """Run a stdio MCP server for a two-seat Tic-Tac-Toe match.

    Convenience entry point for manually exercising this connector (e.g.
    pointing an MCP client such as Claude Code at ``python -m
    agent_game_framework.connectors.mcp.server``) -- not wired into the
    ``agf`` CLI's argument parsing (no ``agf mcp-serve`` subcommand exists
    yet; that wiring, if wanted, is a separate concern from this ticket).
    Both seats ("X" and "O") are driven entirely by whichever MCP client(s)
    call ``submit_action`` for them -- assigning one seat to a bot
    (``RandomBotController``) is KAN-1282's job, not this one.
    """
    from examples.tictactoe import TicTacToeEngine

    match: Match[Any, Any, Any] = Match(TicTacToeEngine(), players=["X", "O"])
    server = build_server(match)
    server.run("stdio")


if __name__ == "__main__":
    main()
