"""Integration tests for ``LiveMatch`` (ADR-0008, ADR-0009): a ``Match``
driven on a background thread, with ``send_chat`` callable at any point --
including while a seat's own ``decide()`` call is itself still blocked.

Per this repo's determinism discipline (``AGENTS.md``), every test here
synchronizes via ``threading.Event``, never a ``time.sleep``-based race: a
fake controller signals "my decide() call has genuinely started" via one
event and blocks on a second until the test explicitly releases it, so
"chat while decide() is in flight" is provably true on every run, not just
plausible under favorable scheduling.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from agent_game_framework.core import (
    AgentTimeoutError,
    IllegalActionError,
    LiveMatch,
    Match,
    SeatDecision,
)
from agent_game_framework.core.conversable import ConversationTurn, TextTurn
from examples.tictactoe.engine import TicTacToeEngine


class _BlockingConversableController:
    """``decide()`` signals it has started (``decide_started``), then blocks
    until ``release()`` is called -- ``respond()`` never blocks, and is
    implemented on the very same instance, mirroring how a real
    ``OpenRouterBackend`` seat is both at once."""

    def __init__(self) -> None:
        self.decide_started = threading.Event()
        self._release = threading.Event()
        self.decide_calls = 0
        self.received_history: list[list[ConversationTurn]] = []

    def decide(self, observation: Any, legal_actions: list[int]) -> SeatDecision[int]:
        self.decide_calls += 1
        self.decide_started.set()
        released = self._release.wait(timeout=5)
        assert released, "test bug: release() was never called"
        return SeatDecision(action=legal_actions[0])

    def release(self) -> None:
        self._release.set()

    def respond(self, history: list[ConversationTurn], incoming: TextTurn) -> TextTurn:
        self.received_history.append(history)
        return TextTurn(text=f"echo: {incoming.text}")


class _FirstLegalActionController:
    """A trivial opponent seat: always plays the first legal action, never
    ``Conversable`` -- keeps the match progressing/finishing without being
    what these tests are actually about."""

    def decide(self, observation: Any, legal_actions: list[int]) -> SeatDecision[int]:
        return SeatDecision(action=legal_actions[0])


class _AlwaysRaisingController:
    """Raises on every ``decide()`` call -- used to prove ``LiveMatch.join()``
    re-raises whatever ``Match.run_to_completion`` raised (here,
    ``AgentTimeoutError`` after ``Match``'s own bounded one-retry policy),
    exactly as it would driving ``Match`` synchronously."""

    def decide(self, observation: Any, legal_actions: list[int]) -> SeatDecision[int]:
        raise RuntimeError("boom")


def test_send_chat_completes_while_the_same_seats_decide_call_is_still_blocked() -> None:
    """The central promise of ADR-0009: a human can chat with a seat at the
    exact moment that seat's own move-``decide()`` call is in flight on the
    background thread, not only in between turns."""
    engine = TicTacToeEngine()
    x_controller = _BlockingConversableController()
    o_controller = _FirstLegalActionController()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )
    live = LiveMatch(match, conversable_seats={"X": x_controller})

    live.start()
    assert x_controller.decide_started.wait(timeout=5), "decide() never started"

    output = live.send_chat("X", "how's it going?")
    assert output == TextTurn(text="echo: how's it going?")

    x_controller.release()
    live.join()

    assert match.is_terminal()
    assert x_controller.decide_calls >= 1


def test_send_chat_history_accumulates_with_correct_roles_in_order() -> None:
    engine = TicTacToeEngine()
    x_controller = _BlockingConversableController()
    o_controller = _FirstLegalActionController()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )
    live = LiveMatch(match, conversable_seats={"X": x_controller})
    live.start()
    assert x_controller.decide_started.wait(timeout=5)

    live.send_chat("X", "first message")
    live.send_chat("X", "second message")

    # The second call's history reflects both sides of the first exchange.
    assert x_controller.received_history[0] == []
    assert x_controller.received_history[1] == [
        ConversationTurn(role="human", content=TextTurn(text="first message")),
        ConversationTurn(role="agent", content=TextTurn(text="echo: first message")),
    ]

    x_controller.release()
    live.join()


def test_send_chat_raises_value_error_for_a_seat_with_no_conversable_registered() -> None:
    engine = TicTacToeEngine()
    x_controller = _FirstLegalActionController()
    o_controller = _FirstLegalActionController()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )
    live = LiveMatch(match, conversable_seats={})

    live.start()
    with pytest.raises(ValueError):
        live.send_chat("X", "hello?")
    live.join()


def test_join_reraises_the_background_threads_agent_timeout_error() -> None:
    """``Match``'s own bounded-retry-then-``AgentTimeoutError`` policy
    (``Match.play_turn``) is completely unchanged by running on a
    background thread -- ``join()`` surfaces it exactly as calling
    ``Match.run_to_completion()`` directly would."""
    engine = TicTacToeEngine()
    x_controller = _AlwaysRaisingController()
    o_controller = _FirstLegalActionController()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )
    live = LiveMatch(match, conversable_seats={})

    live.start()
    with pytest.raises(AgentTimeoutError):
        live.join()


def test_on_turn_and_on_illegal_action_hooks_pass_through_unchanged() -> None:
    """``LiveMatch`` hands its hooks straight to ``Match.run_to_completion``
    with no behavior of its own -- proven by driving a match entirely with
    non-``Conversable`` seats and asserting the hooks still fire normally."""
    engine = TicTacToeEngine()
    seats = {"X": _FirstLegalActionController(), "O": _FirstLegalActionController()}
    match: Match[Any, int, Any] = Match(engine, players=["X", "O"], seats=seats)

    turns: list[str] = []
    illegal: list[IllegalActionError] = []
    live = LiveMatch(
        match,
        conversable_seats={},
        on_turn=lambda player, decision: turns.append(player),
        on_illegal_action=lambda player, decision, exc: illegal.append(exc),
    )

    live.start()
    live.join()

    assert match.is_terminal()
    assert turns  # at least one turn was reported
    assert illegal == []  # both seats always play a legal action
