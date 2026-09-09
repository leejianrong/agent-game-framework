"""Integration tests for the MCP connector (KAN-1281, ADR-0006, SLICES.md V2
integration test plan): the four tools driven over a real, in-process MCP
protocol round trip (``mcp.Client`` connected directly to our ``MCPServer``
instance, per the SDK's own "in tests" in-process mode -- no subprocess, no
real stdio pipe) against a real ``Match``/``TicTacToeEngine``.

Kept thin and few on purpose: a full scripted game played entirely over
real stdio, and the broader V2 test suite, are KAN-1283's job, not this
ticket's.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import Client

from agent_game_framework.connectors.mcp import build_server
from agent_game_framework.core import Match
from examples.tictactoe import TicTacToeEngine


def _make_match() -> Match[Any, Any, Any]:
    return Match(TicTacToeEngine(), players=["X", "O"])


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
