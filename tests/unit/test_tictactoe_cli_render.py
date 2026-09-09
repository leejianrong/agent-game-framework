"""Unit tests for Tic-Tac-Toe's own CLI board renderer
(``examples/tictactoe/cli_render.py``): no external calls, no subprocess.

Moved out of ``tests/unit/test_cli.py`` alongside the renderer itself, which
moved out of the framework's ``cli.py`` into this game's own module so the
shared CLI stays game-agnostic (see ``cli.RENDERER_REGISTRY``'s docstring).
"""

from __future__ import annotations

from typing import Any

from examples.tictactoe.cli_render import render_board, render_observation


class TestRenderBoard:
    def test_empty_board_renders_each_cell_as_its_own_index(self) -> None:
        """Every cell shows its own legal-move number -- the board doubles
        as the input legend, including before any move has been made."""
        board: list[Any] = [None] * 9
        rendered = render_board(board)
        lines = rendered.splitlines()
        assert lines[0] == "0 | 1 | 2"
        assert lines[2] == "3 | 4 | 5"
        assert lines[4] == "6 | 7 | 8"
        # separator matches row width
        assert lines[1] == "-" * len(lines[0])
        assert lines[3] == "-" * len(lines[0])

    def test_mixed_board_renders_marks_row_major_and_numbers_the_rest(self) -> None:
        # X | O | 2
        # ---------
        # 3 | X | 5
        # ---------
        # 6 | 7 | O
        board: list[Any] = ["X", "O", None, None, "X", None, None, None, "O"]
        rendered = render_board(board)
        lines = rendered.splitlines()
        assert lines[0] == "X | O | 2"
        assert lines[2] == "3 | X | 5"
        assert lines[4] == "6 | 7 | O"


def test_render_observation_extracts_the_board_key() -> None:
    """``render_observation`` is the ``cli.RENDERER_REGISTRY`` adapter: it
    pulls ``"board"`` out of a full ``observation_for(...)``-shaped dict
    (which also carries ``"you"``/``"current_players"``) rather than
    requiring the caller to pre-extract it."""
    observation = {"you": "X", "board": ["X"] + [None] * 8, "current_players": ["O"]}
    rendered = render_observation(observation)
    assert rendered.splitlines()[0] == "X | 1 | 2"
