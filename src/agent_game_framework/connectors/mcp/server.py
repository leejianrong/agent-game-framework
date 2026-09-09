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

**Seat assignment (KAN-1282, SLICES.md V2 step 2):** ``build_server`` takes
an optional ``bot_seats`` mapping. Any seat *not* in that mapping is
MCP-client-driven -- the client itself is that seat's controller, simply by
being the caller of ``submit_action`` for it; there is no explicit
"register this client as the controller" step, because a seat's controller
*is* whatever calls ``submit_action`` on its behalf (a real
``SeatController`` for a bot seat, or an MCP client for everything else).
Any seat that *is* in ``bot_seats`` is driven automatically by its
``SeatController`` (typically ``RandomBotController``) via
``_advance_bot_seats`` below, so a full game can complete without a second
MCP client (per the ticket description). This deliberately does not reuse
``Match.play_turn()``/``run_to_completion()``: those require a *complete*
seat map for every current player and raise ``ValueError`` otherwise, which
is the wrong contract here -- an MCP-driven seat has no ``SeatController``
entry by design, waiting instead for an explicit tool call. So
``_advance_bot_seats`` is a small bespoke loop over the same low-level
``Match`` methods this module already uses elsewhere (ADR-0006: a thin
adapter, not a wrapper around a component that doesn't fit).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from agent_game_framework.core import IllegalActionError, Match, PlayerId, SeatController

SERVER_NAME = "agent-game-framework"


def _advance_bot_seats(
    match: Match[Any, Any, Any], bot_seats: dict[PlayerId, SeatController[Any, Any]]
) -> None:
    """Auto-play every current player that has an entry in ``bot_seats``,
    repeatedly, until the match is terminal or a current player is *not* in
    ``bot_seats`` (an MCP-client-driven seat, waiting for an explicit
    ``submit_action`` tool call).

    ``bot_seats`` empty (the default, ``build_server``'s ``bot_seats=None``
    normalized to ``{}``) makes this a no-op on the first check every time --
    preserving KAN-1281's exact behavior of never auto-advancing.

    Deliberately not ``Match.play_turn()``/``run_to_completion()`` -- see
    the module docstring for why those don't fit here.
    """
    while not match.is_terminal():
        current = match.current_players()
        if not current or any(player not in bot_seats for player in current):
            return
        for player in current:
            controller = bot_seats[player]
            observation = match.observation_for(player)
            legal_actions = match.legal_actions(player)
            decision = controller.decide(observation, legal_actions)
            match.submit_action(player, decision.action)


def build_server(
    match: Match[Any, Any, Any],
    bot_seats: dict[PlayerId, SeatController[Any, Any]] | None = None,
    *,
    name: str = SERVER_NAME,
) -> MCPServer[None]:
    """Build an ``MCPServer`` exposing the four tools over ``match``.

    ``match`` is the one ``Match`` instance every tool call below operates
    against -- callers construct it however they like (which engine, which
    players, whether a seat map is attached) before handing it here; this
    function never constructs a ``Match`` itself. Multiple MCP clients (or
    one client driving every seat itself, a valid way to exercise this
    ticket in isolation -- see the module docstring of the tests) all share
    this same instance, so every tool call sees the same, single, current
    state.

    ``bot_seats`` (default ``None``, treated as empty -- no seat is
    bot-driven, matching KAN-1281's original behavior exactly) names which
    seats are auto-played by a ``SeatController`` instead of waiting for an
    MCP client's ``submit_action`` call (KAN-1282). Any current player(s)
    already in ``bot_seats`` are auto-advanced once immediately, before this
    function returns -- covering the case where the *first* mover is a bot
    seat, so it has already played by the time any client makes its first
    call -- and again after every successful ``submit_action`` tool call, so
    bot seats sandwiched between MCP-driven turns play themselves out with
    no second MCP client needed. A failed (``IllegalActionError``)
    ``submit_action`` call never triggers this -- state is unchanged there,
    so there is nothing new to advance.
    """
    seats: dict[PlayerId, SeatController[Any, Any]] = bot_seats or {}
    server: MCPServer[None] = MCPServer(name=name)

    _advance_bot_seats(match, seats)

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
        ``get_state_dump`` round trip -- after also auto-advancing any bot
        seat(s) now up per ``bot_seats``, so the returned state already
        reflects their move(s) too. On ``IllegalActionError`` -- an illegal
        move, or a call out of turn -- raises ``ToolError`` so the MCP layer
        reports a structured tool error (``is_error=True``) back to the
        client instead of crashing or silently no-op'ing; per
        ``Match.submit_action``'s own contract, the match's state is left
        completely unchanged in that case, so no bot-seat advance happens
        either.
        """
        try:
            match.submit_action(player, action)
        except IllegalActionError as exc:
            raise ToolError(str(exc)) from exc
        _advance_bot_seats(match, seats)
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
    Seat "X" is driven entirely by whichever MCP client calls
    ``submit_action`` for it; seat "O" is assigned to ``RandomBotController``
    (KAN-1282) so a full game can complete with only one MCP client
    connected.
    """
    from agent_game_framework.agents import RandomBotController
    from examples.tictactoe import TicTacToeEngine

    match: Match[Any, Any, Any] = Match(TicTacToeEngine(), players=["X", "O"])
    server = build_server(match, bot_seats={"O": RandomBotController()})
    server.run("stdio")


if __name__ == "__main__":
    main()
