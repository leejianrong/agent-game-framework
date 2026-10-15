"""Integration tests for the ``agf play`` game loop (``run_match``, KAN-1279;
turn-loop mechanics moved into ``Match.run_to_completion`` by KAN-1280),
driven in-process against the real ``TicTacToeEngine``/``Match`` -- no
subprocess, no argparse, no real stdin. These exercise ``run_match``'s own
reaction (via the ``on_illegal_action`` hook it hands to
``Match.run_to_completion``) to ``Match.submit_action`` raising
``IllegalActionError`` (the defensive path: a well-behaved
``SeatController`` should never trigger this in practice, since
``HumanCLIController``'s own re-prompt loop is already covered at the unit
level in KAN-1278; here we force it directly with a scripted fake controller
instead of re-testing that re-prompt loop).

As of KAN-1280, ``Match`` owns the seat map -- pass ``seats`` to ``Match(...)``
directly rather than to ``run_match`` (which now only takes an
already-seated ``match``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from agent_game_framework.cli import run_match
from agent_game_framework.core import (
    ConversationTurn,
    Match,
    PlayerId,
    SeatDecision,
    TextTurn,
)
from examples.tictactoe import TicTacToeEngine


def _recording_print_fn(sink: list[str]) -> Any:
    """A ``print_fn`` that records each call's rendered text (joining args
    like the real ``print`` would) into ``sink``, tolerating the zero-arg
    blank-line calls ``run_match`` makes between turns."""

    def _print(*args: Any, **kwargs: Any) -> None:
        sink.append(" ".join(str(a) for a in args))

    return _print


class _ScriptedController:
    """A ``SeatController`` fake that returns a fixed, pre-scripted sequence
    of actions (and, optionally, banter strings) on each ``decide()`` call,
    regardless of ``legal_actions`` -- including actions the engine will
    reject, so tests can force ``Match.submit_action`` to raise
    ``IllegalActionError`` on demand.

    ``banters``, when given, is zipped 1:1 against ``actions`` (KAN-1286):
    this is the fake used to prove ``run_match``'s banter-rendering path --
    which the CLI has carried since KAN-1279/1280 but which no real
    controller (``HumanCLIController``/``RandomBotController``) has ever
    exercised with non-``None`` banter -- actually renders a non-``None``
    ``SeatDecision.banter`` in both text and ``--json`` output. Omitting
    ``banters`` (the pre-existing behavior) means every decision carries no
    banter, as before.
    """

    def __init__(self, actions: list[int], banters: list[str | None] | None = None) -> None:
        self._actions: Iterator[int] = iter(actions)
        self._banters: Iterator[str | None] = iter(
            banters if banters is not None else [None] * len(actions)
        )
        self.calls = 0

    def decide(self, observation: Any, legal_actions: list[int]) -> SeatDecision[int]:
        self.calls += 1
        return SeatDecision(action=next(self._actions), banter=next(self._banters))


class _ScriptedConversableController:
    """A ``_ScriptedController`` that also implements ``Conversable`` --
    the fake used to prove ``run_match``'s ``banter_exchange_seats`` wiring
    (an all-AI seat is one more real ``SeatController`` that just also
    happens to support ``respond()``, exactly as ``OpenRouterBackend``
    does). ``respond()`` always returns a fixed reply prefixed with this
    seat's own label, and records every call it received so a test can
    assert both *how many* times it was addressed and *what* it was told.
    """

    def __init__(
        self, label: str, actions: list[int], banters: list[str | None] | None = None
    ) -> None:
        self._label = label
        self._actions: Iterator[int] = iter(actions)
        self._banters: Iterator[str | None] = iter(
            banters if banters is not None else [None] * len(actions)
        )
        self.respond_calls: list[tuple[list[ConversationTurn], TextTurn]] = []

    def decide(self, observation: Any, legal_actions: list[int]) -> SeatDecision[int]:
        return SeatDecision(action=next(self._actions), banter=next(self._banters))

    def respond(self, history: list[ConversationTurn], incoming: TextTurn) -> TextTurn:
        self.respond_calls.append((list(history), incoming))
        return TextTurn(text=f"{self._label} says: nice try, {incoming.text!r}")


def test_illegal_action_from_submit_action_does_not_advance_the_turn() -> None:
    """X's controller replays cell 0 (already occupied) after its first
    move -- ``Match.submit_action`` raises ``IllegalActionError`` for that
    attempt. ``run_match`` must report it, leave the match's state/current
    player unchanged, and ask X to decide again (not crash, not silently
    hand the turn to O) -- matching this ticket's e2e acceptance criterion
    at the connector layer, with a controller double instead of scripted
    stdin.
    """
    # X: 0 (legal), 0 again (illegal -- occupied), 2, 4, 6 (wins via 2-4-6 diagonal)
    x_controller = _ScriptedController([0, 0, 2, 4, 6])
    # O: 1, 3, 5 -- only 3 calls needed since X wins on its 4th *successful* move
    o_controller = _ScriptedController([1, 3, 5])
    seats: dict[PlayerId, Any] = {"X": x_controller, "O": o_controller}

    engine = TicTacToeEngine()
    match: Match[Any, int, Any] = Match(engine, players=["X", "O"], seats=seats)

    messages: list[str] = []
    run_match(match, json_mode=False, print_fn=_recording_print_fn(messages))

    assert any("Illegal move by X" in line for line in messages)
    assert match.is_terminal()
    assert match.winners() == ["X"]
    # X was asked to decide 5 times (one of them rejected and retried),
    # O only the 3 times it actually got to move.
    assert x_controller.calls == 5
    assert o_controller.calls == 3
    assert match.serialize()["board"] == ["X", "O", "X", "O", "X", "O", "X", None, None]


def test_illegal_action_message_names_the_offending_seat_and_does_not_crash() -> None:
    a_controller = _ScriptedController([-1, 0, 4, 8])  # -1 is out of range: rejected
    b_controller = _ScriptedController([1, 2])

    engine = TicTacToeEngine()
    match: Match[Any, int, Any] = Match(
        engine, players=["A", "B"], seats={"A": a_controller, "B": b_controller}
    )

    messages: list[str] = []
    run_match(
        match,
        json_mode=False,
        print_fn=_recording_print_fn(messages),
    )

    # First decide() call for A produced an out-of-range action; the CLI
    # must have reported it clearly and moved on to A's next decision
    # rather than raising out of run_match.
    assert any("Illegal move by" in line and "A" in line for line in messages)


def test_illegal_action_in_json_mode_emits_a_json_line_not_the_board() -> None:
    import json

    x_controller = _ScriptedController([0, 0, 2, 4, 6])
    o_controller = _ScriptedController([1, 3, 5])

    engine = TicTacToeEngine()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )

    lines: list[str] = []
    run_match(
        match,
        json_mode=True,
        print_fn=_recording_print_fn(lines),
    )

    parsed = [json.loads(line) for line in lines]
    illegal_events = [event for event in parsed if event["type"] == "illegal_action"]
    assert len(illegal_events) == 1
    assert illegal_events[0]["seat"] == "X"
    assert illegal_events[0]["action"] == 0

    result_events = [event for event in parsed if event["type"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["winners"] == ["X"]


def test_banter_is_rendered_alongside_the_move_in_text_mode() -> None:
    """``run_match``'s ``on_turn`` closure has printed a ``' ("<banter>")'``
    suffix since KAN-1279/1280, but until now no test has driven it with a
    controller that actually returns non-``None`` banter (KAN-1286) --
    ``HumanCLIController``/``RandomBotController`` never do. X wins via the
    0/4/8 diagonal in three moves with no illegal attempts, so the game
    completes cleanly while both seats bantering."""
    x_controller = _ScriptedController(
        [0, 4, 8], banters=["taking the corner!", "center is mine", "diagonal, gg"]
    )
    o_controller = _ScriptedController([1, 2], banters=["blocking...", "not again"])

    engine = TicTacToeEngine()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )

    messages: list[str] = []
    run_match(match, json_mode=False, print_fn=_recording_print_fn(messages))

    assert any('X plays 0  ("taking the corner!")' in line for line in messages)
    assert any('O plays 1  ("blocking...")' in line for line in messages)
    assert any('X plays 8  ("diagonal, gg")' in line for line in messages)
    assert match.winners() == ["X"]


def test_banter_is_rendered_as_a_non_null_json_field_in_json_mode() -> None:
    """Same scenario as the text-mode banter test above, but in ``--json``
    mode: each ``"turn"`` event's ``"banter"`` key (present in the envelope
    since KAN-1279/1280) must actually carry the non-``None`` banter text,
    not just be structurally present-but-always-null."""
    import json

    x_controller = _ScriptedController(
        [0, 4, 8], banters=["taking the corner!", "center is mine", "diagonal, gg"]
    )
    o_controller = _ScriptedController([1, 2], banters=["blocking...", "not again"])

    engine = TicTacToeEngine()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )

    lines: list[str] = []
    run_match(match, json_mode=True, print_fn=_recording_print_fn(lines))

    turn_events = [json.loads(line) for line in lines if json.loads(line)["type"] == "turn"]
    assert [event["banter"] for event in turn_events] == [
        "taking the corner!",
        "blocking...",
        "center is mine",
        "not again",
        "diagonal, gg",
    ]


def test_banter_exchange_lets_the_other_ai_seat_reply_with_no_human_involved() -> None:
    """Two ``Conversable`` seats, zero human: every move that carries banter
    gets one spontaneous reply printed from the *other* seat, addressed by
    name -- the all-AI analogue of chat mode, proven here with no
    ``LiveMatch``/threading and no real LLM call involved."""
    x_controller = _ScriptedConversableController(
        "X", [0, 4, 8], banters=["taking the corner!", "center is mine", "diagonal, gg"]
    )
    o_controller = _ScriptedConversableController("O", [1, 2], banters=["blocking...", "not again"])

    engine = TicTacToeEngine()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )

    messages: list[str] = []
    run_match(
        match,
        json_mode=False,
        print_fn=_recording_print_fn(messages),
        banter_exchange_seats={"X": x_controller, "O": o_controller},
    )

    assert match.winners() == ["X"]
    # X moved 3 times, O moved 2 times -- each move's banter earns exactly
    # one reply from the *other* seat, never a reply to oneself.
    assert any("O (reply to X):" in line and "taking the corner!" in line for line in messages)
    assert any("X (reply to O):" in line and "blocking..." in line for line in messages)
    assert len(x_controller.respond_calls) == 2  # replied to O's 2 banters
    assert len(o_controller.respond_calls) == 3  # replied to X's 3 banters


def test_banter_exchange_skips_a_turn_with_no_banter_and_never_recurses() -> None:
    """A move with no banter triggers no reply at all; a reply itself is
    never fed back in as a new incoming message (each seat's ``respond()``
    is called exactly once per *opponent* banter, not once per reply too --
    otherwise this would recurse forever)."""
    x_controller = _ScriptedConversableController("X", [0, 4, 8], banters=[None, None, "gg"])
    o_controller = _ScriptedConversableController("O", [1, 2], banters=[None, None])

    engine = TicTacToeEngine()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )

    messages: list[str] = []
    run_match(
        match,
        json_mode=False,
        print_fn=_recording_print_fn(messages),
        banter_exchange_seats={"X": x_controller, "O": o_controller},
    )

    assert match.winners() == ["X"]
    # Only X's final "gg" move ever carried banter -- exactly one reply,
    # from O, and O's own (banter-less) moves triggered none from X.
    assert sum("(reply to" in line for line in messages) == 1
    assert len(x_controller.respond_calls) == 0
    assert len(o_controller.respond_calls) == 1
    assert o_controller.respond_calls[0][1] == TextTurn(text="gg")


def test_banter_exchange_is_present_as_a_chat_event_in_json_mode() -> None:
    import json

    x_controller = _ScriptedConversableController("X", [0, 4, 8], banters=["hi", None, "gg"])
    o_controller = _ScriptedConversableController("O", [1, 2], banters=[None, None])

    engine = TicTacToeEngine()
    match: Match[Any, int, Any] = Match(
        engine, players=["X", "O"], seats={"X": x_controller, "O": o_controller}
    )

    lines: list[str] = []
    run_match(
        match,
        json_mode=True,
        print_fn=_recording_print_fn(lines),
        banter_exchange_seats={"X": x_controller, "O": o_controller},
    )

    parsed = [json.loads(line) for line in lines]
    chat_events = [event for event in parsed if event["type"] == "chat"]
    assert [event["seat"] for event in chat_events] == ["O", "O"]
    assert all(event["text"].startswith("O says:") for event in chat_events)
