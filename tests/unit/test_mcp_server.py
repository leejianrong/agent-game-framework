"""Unit test for the MCP connector's own input-schema validation (KAN-1281,
SLICES.md V2 unit test plan): "MCP tool input schemas reject a malformed
``submit_action`` payload (wrong type, missing field) before it reaches
``Match``."

No transport, no subprocess: calls straight into the real
``mcp.server.mcpserver.MCPServer.call_tool()`` entry point (the same
validate-then-dispatch path a real client hits), so this exercises the
SDK's actual pydantic-schema validation, not a hand-rolled check of our
own. Proves the "before it reaches ``Match``" half concretely by spying on
``Match.submit_action`` and asserting it is never called, on top of the
state-unchanged check this repo already uses elsewhere for
``IllegalActionError`` (see ``tests/unit/test_match.py``).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from agent_game_framework.connectors.mcp import build_server
from agent_game_framework.core import Match
from examples.tictactoe import TicTacToeEngine

# ToolError is the SDK's own "deliberate, anticipated tool failure"
# exception (see `agent_game_framework/connectors/mcp/server.py`'s module
# docstring) -- the SDK raises it itself for arguments that fail a tool's
# input schema, which is what these tests exercise.


def _make_spied_match() -> tuple[Match[Any, Any, Any], MagicMock]:
    """A real ``Match`` over ``TicTacToeEngine``, with ``submit_action``
    replaced by a ``MagicMock`` that still delegates to the real method
    (``wraps=``) -- so a call that *does* get through still works exactly
    as before, while letting the test assert whether it happened at all.
    """
    match: Match[Any, Any, Any] = Match(TicTacToeEngine(), players=["X", "O"])
    spy = MagicMock(wraps=match.submit_action)
    match.submit_action = spy  # type: ignore[method-assign]
    return match, spy


def test_wrong_type_action_is_rejected_before_reaching_match() -> None:
    match, spy = _make_spied_match()
    server = build_server(match)
    before = match.serialize()

    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("submit_action", {"player": "X", "action": "not-an-int"}))

    spy.assert_not_called()
    assert match.serialize() == before


def test_missing_action_field_is_rejected_before_reaching_match() -> None:
    match, spy = _make_spied_match()
    server = build_server(match)
    before = match.serialize()

    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("submit_action", {"player": "X"}))

    spy.assert_not_called()
    assert match.serialize() == before


def test_missing_player_field_is_rejected_before_reaching_match() -> None:
    match, spy = _make_spied_match()
    server = build_server(match)
    before = match.serialize()

    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("submit_action", {"action": 0}))

    spy.assert_not_called()
    assert match.serialize() == before


def test_a_legal_payload_is_not_rejected_and_does_reach_match() -> None:
    """Control case: proves the above tests fail for the reason claimed
    (schema rejection), not because ``submit_action`` is broken or
    unreachable in general."""
    match, spy = _make_spied_match()
    server = build_server(match)

    asyncio.run(server.call_tool("submit_action", {"player": "X", "action": 0}))

    spy.assert_called_once_with("X", 0)
