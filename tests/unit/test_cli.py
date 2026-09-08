"""Unit tests for the ``agf`` CLI's own parsing/rendering helpers (KAN-1279,
ADR-0006): no external calls, no subprocess -- these are plain functions
tested directly, cheaply, and in isolation from argparse/``Match``/stdin.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_game_framework.agents import HumanCLIController, RandomBotController
from agent_game_framework.cli import (
    GAME_REGISTRY,
    SeatSpecError,
    build_controller,
    parse_seat_arg,
    render_tictactoe_board,
)


def test_game_registry_has_exactly_tictactoe() -> None:
    """Only Tic-Tac-Toe is registered for now (this ticket's scope) -- but
    the registry is a dict, not a hardcoded if/else, so adding a second game
    later is a one-line addition here."""
    assert set(GAME_REGISTRY) == {"tictactoe"}


class TestParseSeatArg:
    def test_splits_id_and_controller_spec(self) -> None:
        assert parse_seat_arg("X=human") == ("X", "human")
        assert parse_seat_arg("O=bot:random") == ("O", "bot:random")

    def test_id_and_spec_may_contain_no_further_structure_assumptions(self) -> None:
        # id itself is an arbitrary PlayerId string; only the *first* '=' splits.
        assert parse_seat_arg("player-1=bot:random") == ("player-1", "bot:random")

    @pytest.mark.parametrize("raw", ["human", "Xhuman", ""])
    def test_missing_equals_sign_raises(self, raw: str) -> None:
        with pytest.raises(SeatSpecError):
            parse_seat_arg(raw)

    def test_missing_id_before_equals_raises(self) -> None:
        with pytest.raises(SeatSpecError):
            parse_seat_arg("=human")

    def test_missing_spec_after_equals_raises(self) -> None:
        with pytest.raises(SeatSpecError):
            parse_seat_arg("X=")


class TestBuildController:
    def test_human_spec_builds_human_cli_controller(self) -> None:
        controller = build_controller("human")
        assert isinstance(controller, HumanCLIController)

    def test_bot_random_spec_builds_random_bot_controller(self) -> None:
        controller = build_controller("bot:random")
        assert isinstance(controller, RandomBotController)

    @pytest.mark.parametrize("spec", ["bot", "bot:minimax", "llm:openrouter/foo", "HUMAN", ""])
    def test_unknown_spec_raises(self, spec: str) -> None:
        with pytest.raises(SeatSpecError):
            build_controller(spec)


class TestRenderTicTacToeBoard:
    def test_empty_board_renders_all_placeholders(self) -> None:
        board: list[Any] = [None] * 9
        rendered = render_tictactoe_board(board)
        lines = rendered.splitlines()
        assert lines[0] == ". | . | ."
        assert lines[2] == ". | . | ."
        assert lines[4] == ". | . | ."
        # separator matches row width
        assert lines[1] == "-" * len(lines[0])
        assert lines[3] == "-" * len(lines[0])

    def test_mixed_board_renders_marks_row_major(self) -> None:
        # X | O | .
        # ---------
        # . | X | .
        # ---------
        # . | . | O
        board: list[Any] = ["X", "O", None, None, "X", None, None, None, "O"]
        rendered = render_tictactoe_board(board)
        lines = rendered.splitlines()
        assert lines[0] == "X | O | ."
        assert lines[2] == ". | X | ."
        assert lines[4] == ". | . | O"
