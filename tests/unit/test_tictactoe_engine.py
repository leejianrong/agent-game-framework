"""Unit tests for ``TicTacToeEngine`` (KAN-1277, ADR-0003, ADR-0007): no
external calls, no subprocess. Exercises the engine directly (no ``Match``)
one behavior at a time -- see ``tests/integration/test_tictactoe_match.py``
for the end-to-end-through-``Match`` coverage.

Players are deliberately not named "X"/"O" in most tests, to prove the
engine never hardcodes those literal strings as ``PlayerId`` values --
``players[0]`` is just whoever moves first.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_game_framework.core import IllegalActionError
from examples.tictactoe import TicTacToeEngine, TicTacToeState

PLAYERS = ["Alice", "Bob"]


@pytest.fixture
def engine() -> TicTacToeEngine:
    return TicTacToeEngine()


@pytest.fixture
def state(engine: TicTacToeEngine) -> TicTacToeState:
    return engine.initial_state(list(PLAYERS), {})


def _play(engine: TicTacToeEngine, state: TicTacToeState, moves: list[int]) -> TicTacToeState:
    """Apply ``moves`` in turn order (Alice, Bob, Alice, Bob, ...), returning
    the resulting state."""
    for i, cell in enumerate(moves):
        player = PLAYERS[i % 2]
        state = engine.apply_action(state, player, cell)
    return state


# -- initial_state / current_players ----------------------------------------


def test_initial_state_requires_exactly_two_players(engine: TicTacToeEngine) -> None:
    with pytest.raises(ValueError, match="exactly 2 players"):
        engine.initial_state(["A", "B", "C"], {})


def test_current_players_is_the_first_player_in_turn_order(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    # players[0] ("Alice") is the conventional "X" seat: moves first.
    assert engine.current_players(state) == ["Alice"]


def test_current_players_alternates_after_a_move(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    state = engine.apply_action(state, "Alice", 0)
    assert engine.current_players(state) == ["Bob"]


def test_current_players_is_empty_once_terminal(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    # Alice wins the top row: Alice 0, Bob 3, Alice 1, Bob 4, Alice 2.
    state = _play(engine, state, [0, 3, 1, 4, 2])
    assert engine.is_terminal(state) is True
    assert engine.current_players(state) == []


# -- legal_actions ------------------------------------------------------------


def test_legal_actions_lists_all_nine_cells_at_the_start(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    assert engine.legal_actions(state, "Alice") == list(range(9))


def test_legal_actions_excludes_occupied_cells(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    state = engine.apply_action(state, "Alice", 4)
    state = engine.apply_action(state, "Bob", 0)
    assert 4 not in engine.legal_actions(state, "Alice")
    assert 0 not in engine.legal_actions(state, "Alice")
    assert engine.legal_actions(state, "Alice") == [1, 2, 3, 5, 6, 7, 8]


def test_legal_actions_is_empty_for_the_player_not_up(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    assert engine.legal_actions(state, "Bob") == []


def test_legal_actions_is_empty_once_terminal(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    state = _play(engine, state, [0, 3, 1, 4, 2])  # Alice wins the top row.
    assert engine.legal_actions(state, "Alice") == []
    assert engine.legal_actions(state, "Bob") == []


# -- apply_action: illegal actions --------------------------------------------


def test_apply_action_rejects_an_occupied_cell(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    state = engine.apply_action(state, "Alice", 0)
    before = engine.serialize(state)

    with pytest.raises(IllegalActionError, match="occupied"):
        engine.apply_action(state, "Bob", 0)

    assert engine.serialize(state) == before


@pytest.mark.parametrize("cell", [-1, 9, 100])
def test_apply_action_rejects_an_out_of_range_cell(
    engine: TicTacToeEngine, state: TicTacToeState, cell: int
) -> None:
    before = engine.serialize(state)

    with pytest.raises(IllegalActionError, match="out of range"):
        engine.apply_action(state, "Alice", cell)

    assert engine.serialize(state) == before


def test_apply_action_rejects_a_player_who_is_not_up(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    before = engine.serialize(state)

    with pytest.raises(IllegalActionError):
        engine.apply_action(state, "Bob", 0)  # it's Alice's turn

    assert engine.serialize(state) == before


def test_apply_action_does_not_mutate_the_passed_in_state(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    original = engine.serialize(state)
    engine.apply_action(state, "Alice", 0)

    assert engine.serialize(state) == original


# -- winners: all 8 winning lines ---------------------------------------------

# For each winning line, script a game where Alice (players[0]) claims every
# cell in the line and Bob claims two cells outside it -- Alice's 3rd move
# (the game's 5th ply) completes the line and ends the match.
_WINNING_LINE_CASES = [
    ("top row", (0, 1, 2)),
    ("middle row", (3, 4, 5)),
    ("bottom row", (6, 7, 8)),
    ("left column", (0, 3, 6)),
    ("middle column", (1, 4, 7)),
    ("right column", (2, 5, 8)),
    ("main diagonal", (0, 4, 8)),
    ("anti-diagonal", (2, 4, 6)),
]


@pytest.mark.parametrize("name, line", _WINNING_LINE_CASES, ids=[c[0] for c in _WINNING_LINE_CASES])
def test_winners_detects_every_winning_line(
    engine: TicTacToeEngine,
    state: TicTacToeState,
    name: str,
    line: tuple[int, int, int],
) -> None:
    a, b, c = line
    other_cells = [cell for cell in range(9) if cell not in line]
    moves = [a, other_cells[0], b, other_cells[1], c]

    state = _play(engine, state, moves)

    assert engine.is_terminal(state) is True
    assert engine.winners(state) == ["Alice"]


def test_winners_is_empty_while_non_terminal(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    assert engine.is_terminal(state) is False
    assert engine.winners(state) == []


def test_winners_is_empty_on_a_full_board_draw(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    # Final board (row-major):
    #   X O X
    #   X O O
    #   O X X
    # No 3-in-a-row for either player, board full.
    moves = [0, 1, 2, 4, 3, 5, 7, 6, 8]
    state = _play(engine, state, moves)

    assert engine.is_terminal(state) is True
    assert all(cell is not None for cell in state.board)
    assert engine.winners(state) == []


# -- observation_for -----------------------------------------------------------


def test_observation_for_has_no_hidden_information(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    state = engine.apply_action(state, "Alice", 4)

    alice_view = engine.observation_for(state, "Alice")
    bob_view = engine.observation_for(state, "Bob")

    assert alice_view["board"] == bob_view["board"]
    assert alice_view["board"] == state.board
    assert alice_view["you"] == "Alice"
    assert bob_view["you"] == "Bob"
    assert alice_view["current_players"] == ["Bob"]


# -- serialize / deserialize ----------------------------------------------------


def test_serialize_includes_schema_version(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    data = engine.serialize(state)
    assert data["schema_version"] == 1


def test_serialize_deserialize_round_trips_a_mid_game_state(
    engine: TicTacToeEngine, state: TicTacToeState
) -> None:
    state = _play(engine, state, [4, 0, 8])  # a few moves into the game
    dumped = engine.serialize(state)

    restored = engine.deserialize(dumped)

    assert engine.serialize(restored) == dumped
    assert restored.players == state.players
    assert restored.board == state.board
    assert restored.turn_index == state.turn_index
    # Play continues identically from the restored state.
    assert engine.current_players(restored) == engine.current_players(state)
    assert engine.legal_actions(restored, "Bob") == engine.legal_actions(state, "Bob")


def test_deserialize_rejects_an_unknown_schema_version(engine: TicTacToeEngine) -> None:
    bad_data: dict[str, Any] = {
        "schema_version": 999,
        "players": PLAYERS,
        "board": [None] * 9,
        "turn_index": 0,
    }

    with pytest.raises(ValueError, match="schema_version"):
        engine.deserialize(bad_data)
