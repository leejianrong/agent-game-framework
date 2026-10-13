"""``run_live_match_with_chat`` when stdin does not cooperate with the match.

Regression for a hang: the loop blocked on ``input_fn()`` even after the match
had ended, so a match whose last move was the opponent's left the CLI waiting
for a keypress, and an end-of-input then reported "ended before the match
finished" (exit 4) for a finished match.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from agent_game_framework.cli import (
    ChattableHumanController,
    PendingMoveChannel,
    run_live_match_with_chat,
)
from agent_game_framework.core import Match, SeatDecision, TextTurn
from examples.tictactoe import TicTacToeEngine


class Opponent:
    """A scripted, chat-capable seat. ``before_move`` runs inside ``decide``."""

    def __init__(self, moves: list[int], before_move: Callable[[], None] = lambda: None) -> None:
        self._moves = list(moves)
        self._before_move = before_move

    def decide(self, observation: Any, legal_actions: list[int]) -> SeatDecision[int]:
        self._before_move()
        return SeatDecision(action=self._moves.pop(0))

    def respond(self, history: list[Any], incoming: TextTurn) -> TextTurn:
        return TextTurn(text="hi")


# X: 0, 1, 8 against O: 3, 4, 5 -> O completes the middle row on ITS move.
HUMAN_MOVES = ["0", "1", "8"]
OPPONENT_MOVES = [3, 4, 5]


def drive(input_fn: Callable[[], str], opponent: Opponent) -> tuple[int | None, list[str]]:
    channel: PendingMoveChannel[Any, Any] = PendingMoveChannel()
    match: Match[Any, Any, Any] = Match(
        TicTacToeEngine(),
        players=["X", "O"],
        seats={"X": ChattableHumanController(channel), "O": opponent},
    )
    out: list[str] = []
    result: list[int] = []

    def run() -> None:
        result.append(
            run_live_match_with_chat(
                match,
                human_id="X",
                opponent_id="O",
                opponent_controller=opponent,
                channel=channel,
                json_mode=False,
                renderer=None,
                print_fn=lambda *a, **k: out.append(" ".join(map(str, a))),
                input_fn=input_fn,
            )
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=15)
    return (result[0] if result else None), out


def test_a_match_that_ends_on_the_opponents_move_returns_without_another_line_of_input() -> None:
    lines = iter(HUMAN_MOVES)
    never = threading.Event()

    def input_fn() -> str:
        try:
            return next(lines)
        except StopIteration:
            never.wait()  # an open terminal where the user has typed nothing more
            raise EOFError from None

    opponent = Opponent(OPPONENT_MOVES)
    slow = threading.Event()
    threading.Timer(0.4, slow.set).start()
    opponent._before_move = lambda: None if opponent._moves[1:] else slow.wait(10)  # noqa: SLF001
    code, out = drive(input_fn, opponent)

    assert code == 0, out
    assert any("Winner" in line for line in out)


def test_end_of_input_while_the_opponent_is_still_thinking_is_not_an_error() -> None:
    lines = iter(HUMAN_MOVES)
    gate = threading.Event()
    threading.Timer(0.5, gate.set).start()

    def input_fn() -> str:
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    def slow_final_move() -> None:
        if not opponent._moves[1:]:  # noqa: SLF001  (the last move is the slow one)
            gate.wait(10)

    opponent = Opponent(OPPONENT_MOVES, before_move=slow_final_move)
    code, out = drive(input_fn, opponent)

    assert code == 0, out
    assert any("Winner" in line for line in out)


def test_end_of_input_while_the_human_is_expected_to_move_still_exits_four() -> None:
    def input_fn() -> str:
        raise EOFError

    code, out = drive(input_fn, Opponent(OPPONENT_MOVES))

    assert code == 4, out
    assert any("Input ended" in line for line in out)
