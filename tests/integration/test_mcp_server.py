"""Integration tests for the MCP connector (KAN-1281, KAN-1282, ADR-0006,
SLICES.md V2 integration test plan): the four tools driven over a real,
in-process MCP protocol round trip (``mcp.Client`` connected directly to our
``MCPServer`` instance, per the SDK's own "in tests" in-process mode -- no
subprocess, no real stdio pipe) against a real ``Match``/``TicTacToeEngine``,
plus (KAN-1282) ``bot_seats`` auto-advancing seats not driven by any client.

Kept thin and few on purpose: a full scripted game played entirely over
real stdio, and the broader V2 test suite, are KAN-1283's job, not this
ticket's.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from mcp import Client

from agent_game_framework.agents import RandomBotController
from agent_game_framework.connectors.mcp import build_server
from agent_game_framework.core import Match
from examples.tictactoe import TicTacToeEngine


def _make_match(players: list[str] | None = None) -> Match[Any, Any, Any]:
    return Match(TicTacToeEngine(), players=players or ["X", "O"])


def test_get_observation_and_list_legal_actions_reflect_match_state() -> None:
    match = _make_match()
    # Advance the real match directly (bypassing MCP) so the tools have
    # something non-initial to reflect.
    match.submit_action("X", 4)
    server = build_server(match)

    async def scenario() -> None:
        async with Client(server) as client:
            obs = await client.call_tool("get_observation", {"player": "O"})
            assert obs.structured_content == match.observation_for("O")

            legal = await client.call_tool("list_legal_actions", {"player": "O"})
            assert legal.structured_content == {"result": match.legal_actions("O")}

    asyncio.run(scenario())


def test_legal_submit_action_advances_match_state() -> None:
    match = _make_match()
    server = build_server(match)

    async def scenario() -> None:
        async with Client(server) as client:
            result = await client.call_tool("submit_action", {"player": "X", "action": 4})
            assert result.is_error is False

    asyncio.run(scenario())

    # Verified directly against Match, not just the tool's own response.
    assert match.serialize()["board"][4] == "X"
    assert match.current_players() == ["O"]


def test_illegal_submit_action_returns_structured_error_and_leaves_state_unchanged() -> None:
    match = _make_match()
    match.submit_action("X", 0)  # cell 0 now occupied; it's O's turn
    server = build_server(match)
    before = match.serialize()

    async def scenario() -> Any:
        async with Client(server) as client:
            # O is up, but targets an already-occupied cell.
            return await client.call_tool("submit_action", {"player": "O", "action": 0})

    result = asyncio.run(scenario())

    assert result.is_error is True
    assert not result.content[0].text.startswith("Traceback")  # a structured error, not a crash
    assert match.serialize() == before


def test_full_game_completes_via_one_client_with_bot_seat_auto_playing() -> None:
    """KAN-1282, SLICES.md V2 step 2: one MCP client drives seat "X" only;
    seat "O" is entirely auto-played by ``RandomBotController`` via
    ``bot_seats`` -- no second client ever calls ``submit_action`` for "O".
    """
    match = _make_match()
    bot_seats = {"O": RandomBotController(random.Random(42))}
    server = build_server(match, bot_seats)

    async def scenario() -> None:
        async with Client(server) as client:
            # Only ever calls tools on behalf of "X" -- "O" is never named
            # in a submit_action call from this (or any) client.
            while not match.is_terminal():
                legal = await client.call_tool("list_legal_actions", {"player": "X"})
                action = legal.structured_content["result"][0]
                result = await client.call_tool("submit_action", {"player": "X", "action": action})
                assert result.is_error is False

    asyncio.run(scenario())

    # The game actually finished, and O's cells were filled despite no
    # client ever having called submit_action on its behalf.
    assert match.is_terminal()
    board = match.serialize()["board"]
    assert "O" in board


def test_bot_first_mover_has_already_played_before_any_client_call() -> None:
    """If the first player to act is a bot seat, ``build_server`` auto-plays
    it immediately -- before any MCP client makes its first tool call
    (covers the "advance before any client call" bootstrap path).
    """
    # players[0] moves first (see TicTacToeEngine's module docstring); put
    # the bot seat ("O") first so it's the one that must move before any
    # client ever connects.
    match = _make_match(players=["O", "X"])
    bot_seats = {"O": RandomBotController(random.Random(7))}

    server = build_server(match, bot_seats)
    assert server is not None  # constructed only for its auto-advance side effect

    # No tool call, no client, has happened yet -- this is all direct
    # Match inspection.
    assert match.current_players() == ["X"]
    board = match.serialize()["board"]
    assert board.count("O") == 1
    assert board.count(None) == 8
