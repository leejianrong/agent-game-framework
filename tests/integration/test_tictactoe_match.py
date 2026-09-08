"""Integration tests for ``TicTacToeEngine`` driven through the real
``Match`` orchestrator (KAN-1277, ADR-0003, ADR-0007): in-process, no
subprocess, no CLI/MCP -- those connectors are separate, later tickets.

Proves the real engine composes correctly with the real orchestrator
end-to-end, the same way ``tests/integration/test_match_turn_loop.py`` does
for the ``CounterEngine`` fake, but with a real game's real rules.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_game_framework.core import IllegalActionError, Match
from examples.tictactoe import TicTacToeEngine, TicTacToeState

PLAYERS = ["Alice", "Bob"]

TicTacToeMatch = Match[TicTacToeState, int, dict[str, Any]]


def _make_match() -> TicTacToeMatch:
    return Match(TicTacToeEngine(), list(PLAYERS))


def test_match_drives_tictactoe_to_a_win() -> None:
    """Alice claims the top row (0, 1, 2); Bob plays two cells elsewhere.
    The turn loop is driven purely off ``current_players()``/
    ``legal_actions()``, not an out-of-band assumption about seat order.
    """
    match = _make_match()
    scripted_moves = [0, 3, 1, 4, 2]  # Alice, Bob, Alice, Bob, Alice

    turns = 0
    for cell in scripted_moves:
        turns += 1
        assert turns <= 9, "turn loop did not terminate"
        acting = match.current_players()
        assert len(acting) == 1, "tic-tac-toe is strict turn order, never simultaneous"
        player = acting[0]
        assert cell in match.legal_actions(player)
        match.submit_action(player, cell)

    assert match.is_terminal() is True
    assert match.winners() == ["Alice"]
    assert match.current_players() == []


def test_match_drives_tictactoe_to_a_full_board_draw() -> None:
    match = _make_match()
    # Same draw sequence as tests/unit/test_tictactoe_engine.py's draw test:
    #   X O X
    #   X O O
    #   O X X
    scripted_moves = [0, 1, 2, 4, 3, 5, 7, 6, 8]

    for cell in scripted_moves:
        player = match.current_players()[0]
        match.submit_action(player, cell)

    assert match.is_terminal() is True
    assert match.winners() == []
    assert match.current_players() == []


def test_match_rejects_out_of_turn_submission_against_the_real_engine() -> None:
    match = _make_match()
    match.submit_action("Alice", 0)  # now it's Bob's turn
    before = match.serialize()

    with pytest.raises(IllegalActionError):
        match.submit_action("Alice", 1)

    assert match.serialize() == before
    assert match.current_players() == ["Bob"]


def test_match_state_round_trips_mid_game_through_tictactoe() -> None:
    original = _make_match()
    original.submit_action("Alice", 4)
    original.submit_action("Bob", 0)
    dumped = original.serialize()
    assert "schema_version" in dumped

    resumed = _make_match()
    resumed.deserialize(dumped)
    assert resumed.serialize() == dumped
    assert resumed.current_players() == original.current_players()
