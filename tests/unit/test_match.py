"""Unit tests for the ``Match`` orchestrator (KAN-1275, ADR-0003): no
external calls, no subprocess. Exercises ``Match`` against the
``CounterEngine`` fake defined in ``tests/conftest.py``, one behavior at a
time.

Also covers ``Match.play_turn``'s seat-map-driven turn mechanics (KAN-1280,
PLAN.md Shape S2): the ``ValueError`` programmer-error signals for a missing
seat map/entry, and the ``on_turn``/``on_illegal_action`` hook contract, all
still against the ``CounterEngine`` fake -- full-game integration coverage of
the seat-map-driven API lives in ``tests/integration``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from agent_game_framework.core import IllegalActionError, Match, SeatDecision

if TYPE_CHECKING:
    from conftest import CounterEngine, CounterMatch

INC = "inc"


class _FixedController:
    """A ``SeatController`` test double that always returns the same
    ``action``, regardless of ``legal_actions`` -- deliberately simple, so
    tests can force a specific legal or illegal outcome on demand."""

    def __init__(self, action: str) -> None:
        self._action = action

    def decide(self, observation: Any, legal_actions: list[str]) -> SeatDecision[str]:
        return SeatDecision(action=self._action)


def test_current_players_delegates_to_engine(make_match: Callable[..., CounterMatch]) -> None:
    match = make_match(players=["A", "B"])
    assert match.current_players() == ["A"]


def test_legal_actions_delegates_to_engine(make_match: Callable[..., CounterMatch]) -> None:
    match = make_match(players=["A", "B"])
    assert match.legal_actions("A") == [INC]
    # Not this player's turn -- engine returns no legal actions for them.
    assert match.legal_actions("B") == []


def test_submit_action_accepts_the_player_who_is_up(
    make_match: Callable[..., CounterMatch],
) -> None:
    match = make_match(players=["A", "B"])
    match.submit_action("A", INC)
    assert match.current_players() == ["B"]


def test_submit_action_rejects_a_player_not_currently_up(
    make_match: Callable[..., CounterMatch],
) -> None:
    match = make_match(players=["A", "B"])
    before = match.serialize()

    with pytest.raises(IllegalActionError):
        match.submit_action("B", INC)

    # Rejected before ever reaching the engine's apply_action: state is
    # byte-for-byte (via serialize()) unchanged.
    assert match.serialize() == before


def test_submit_action_illegal_action_leaves_state_unchanged(
    make_match: Callable[..., CounterMatch],
) -> None:
    match = make_match(players=["A", "B"])
    before = match.serialize()

    with pytest.raises(IllegalActionError):
        match.submit_action("A", "cheat")

    assert match.serialize() == before


def test_is_terminal_and_winners_delegate_to_engine(
    make_match: Callable[..., CounterMatch],
) -> None:
    match = make_match(players=["A", "B"], target=1)
    assert match.is_terminal() is False
    assert match.winners() == []

    match.submit_action("A", INC)

    assert match.is_terminal() is True
    assert match.winners() == ["A"]


def test_observation_for_delegates_to_engine(make_match: Callable[..., CounterMatch]) -> None:
    match = make_match(players=["A", "B"])
    observation = match.observation_for("A")
    assert observation == {
        "you": "A",
        "scores": {"A": 0, "B": 0},
        "current_players": ["A"],
    }


def test_serialize_includes_schema_version(make_match: Callable[..., CounterMatch]) -> None:
    match = make_match(players=["A", "B"])
    data = match.serialize()
    assert data["schema_version"] == 1


def test_deserialize_round_trips_through_match(
    make_match: Callable[..., CounterMatch], counter_engine: CounterEngine
) -> None:
    match = make_match(players=["A", "B"])
    match.submit_action("A", INC)
    dumped = match.serialize()

    restored: CounterMatch = Match(counter_engine, players=["A", "B"])
    restored.deserialize(dumped)

    assert restored.serialize() == dumped
    assert restored.current_players() == match.current_players()


def test_deserialize_rejects_unknown_schema_version(
    make_match: Callable[..., CounterMatch],
) -> None:
    match = make_match(players=["A", "B"])
    bad_data: dict[str, Any] = {**match.serialize(), "schema_version": 999}

    with pytest.raises(ValueError, match="schema_version"):
        match.deserialize(bad_data)


class TestPlayTurn:
    """``Match.play_turn`` (KAN-1280): the seat-map-driven turn mechanics
    that back ``run_to_completion`` and the CLI's turn loop."""

    def test_requires_a_seat_map_to_have_been_provided(
        self, make_match: Callable[..., CounterMatch]
    ) -> None:
        match = make_match(players=["A", "B"])  # no `seats=` passed
        with pytest.raises(ValueError, match="seat map"):
            match.play_turn()

    def test_requires_every_current_player_to_have_a_seat_entry(
        self, counter_engine: CounterEngine
    ) -> None:
        match: CounterMatch = Match(
            counter_engine, players=["A", "B"], seats={"A": _FixedController(INC)}
        )
        match.play_turn()  # A is up first and has an entry; advances to B's turn.
        assert match.current_players() == ["B"]

        with pytest.raises(ValueError, match="no SeatController registered for player 'B'"):
            match.play_turn()  # B has no entry in the seat map.

    def test_calls_on_turn_after_a_successful_decide_and_submit(
        self, counter_engine: CounterEngine
    ) -> None:
        seats = {"A": _FixedController(INC), "B": _FixedController(INC)}
        match: CounterMatch = Match(counter_engine, players=["A", "B"], seats=seats)

        events: list[tuple[str, str]] = []
        match.play_turn(on_turn=lambda player, decision: events.append((player, decision.action)))

        assert events == [("A", INC)]
        assert match.current_players() == ["B"]

    def test_propagates_illegal_action_error_when_no_hook_is_given(
        self, counter_engine: CounterEngine
    ) -> None:
        seats = {"A": _FixedController("cheat")}
        match: CounterMatch = Match(counter_engine, players=["A", "B"], seats=seats)
        before = match.serialize()

        with pytest.raises(IllegalActionError):
            match.play_turn()

        # Rejected before the engine's state ever moved.
        assert match.serialize() == before
        assert match.current_players() == ["A"]

    def test_on_illegal_action_hook_fires_and_leaves_the_same_player_up_to_retry(
        self, counter_engine: CounterEngine
    ) -> None:
        seats = {"A": _FixedController("cheat"), "B": _FixedController(INC)}
        match: CounterMatch = Match(counter_engine, players=["A", "B"], seats=seats)
        before = match.serialize()

        calls: list[tuple[str, str, str]] = []
        match.play_turn(
            on_illegal_action=lambda player, decision, exc: calls.append(
                (player, decision.action, str(exc))
            )
        )

        assert len(calls) == 1
        assert calls[0][0] == "A"
        assert calls[0][1] == "cheat"
        # State is unchanged and A is still up -- calling play_turn() again
        # re-asks A rather than silently advancing to B.
        assert match.serialize() == before
        assert match.current_players() == ["A"]


class TestRunToCompletion:
    """``Match.run_to_completion`` (KAN-1280): loops ``play_turn`` until
    ``is_terminal()``. Full-game coverage against a real engine lives in
    ``tests/integration``; this exercises the loop mechanics themselves
    against the ``CounterEngine`` fake.
    """

    def test_drives_a_full_game_to_completion_via_the_seat_map(
        self, counter_engine: CounterEngine
    ) -> None:
        seats = {"A": _FixedController(INC), "B": _FixedController(INC)}
        match: CounterMatch = Match(
            counter_engine, players=["A", "B"], config={"target": 3}, seats=seats
        )

        turns: list[str] = []
        match.run_to_completion(on_turn=lambda player, decision: turns.append(player))

        assert match.is_terminal() is True
        assert match.winners() == ["A"]
        # A reaches target=3 on its 3rd turn; B gets 2 turns in between.
        assert turns == ["A", "B", "A", "B", "A"]

    def test_reports_illegal_actions_via_the_hook_and_still_completes(
        self, counter_engine: CounterEngine
    ) -> None:
        class _OnceWrongController:
            """Returns an illegal action once, then always the legal one."""

            def __init__(self) -> None:
                self._first = True

            def decide(self, observation: Any, legal_actions: list[str]) -> SeatDecision[str]:
                if self._first:
                    self._first = False
                    return SeatDecision(action="cheat")
                return SeatDecision(action=INC)

        seats = {"A": _OnceWrongController(), "B": _FixedController(INC)}
        match: CounterMatch = Match(
            counter_engine, players=["A", "B"], config={"target": 1}, seats=seats
        )

        illegal_calls: list[str] = []
        match.run_to_completion(
            on_illegal_action=lambda player, decision, exc: illegal_calls.append(player)
        )

        assert illegal_calls == ["A"]
        assert match.is_terminal() is True
        assert match.winners() == ["A"]
