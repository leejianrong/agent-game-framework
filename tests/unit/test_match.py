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

from agent_game_framework.core import AgentTimeoutError, IllegalActionError, Match, SeatDecision

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


class _RaisingOnceController:
    """A ``SeatController`` test double whose ``decide()`` raises ``exc`` on
    its first call, then returns ``SeatDecision(action=action)`` on every
    call after that -- proves ``Match``'s bounded-retry-then-succeed path
    (KAN-1285): a controller that failed once but recovers on the immediate
    retry never surfaces ``AgentTimeoutError`` at all.
    """

    def __init__(self, action: str, exc: Exception) -> None:
        self._action = action
        self._exc = exc
        self.calls = 0

    def decide(self, observation: Any, legal_actions: list[str]) -> SeatDecision[str]:
        self.calls += 1
        if self.calls == 1:
            raise self._exc
        return SeatDecision(action=self._action)


class _AlwaysRaisingController:
    """A ``SeatController`` test double whose ``decide()`` always raises --
    proves ``Match`` gives up after exactly one retry and raises
    ``AgentTimeoutError`` rather than retrying unboundedly or hanging
    (KAN-1285). ``exc_factory`` is called fresh each time so a test can
    assert on which of the two distinct exception instances ended up
    chained as ``AgentTimeoutError.__cause__``.
    """

    def __init__(self, exc_factory: Callable[[], Exception]) -> None:
        self._exc_factory = exc_factory
        self.calls = 0

    def decide(self, observation: Any, legal_actions: list[str]) -> SeatDecision[str]:
        self.calls += 1
        raise self._exc_factory()


class TestPlayTurnAgentErrors:
    """``Match.play_turn``'s handling of a ``SeatController.decide()`` call
    that itself *raises* (KAN-1285, SLICES.md V3 step 2) -- a distinct
    failure mode from ``TestPlayTurn`` above, which covers a well-formed but
    *returned* illegal action (``IllegalActionError``/``on_illegal_action``).
    Here, no ``SeatDecision`` is ever produced at all, so nothing is ever
    submitted; ``Match``'s bounded retry-once-then-``AgentTimeoutError``
    policy is new production code this ticket adds, unlike the
    ``on_illegal_action`` path, which this class deliberately does not
    touch.
    """

    def test_retries_once_and_succeeds_on_the_second_decide_call(
        self, counter_engine: CounterEngine
    ) -> None:
        controller = _RaisingOnceController(INC, RuntimeError("simulated network timeout"))
        seats = {"A": controller, "B": _FixedController(INC)}
        match: CounterMatch = Match(counter_engine, players=["A", "B"], seats=seats)

        match.play_turn()  # must not raise -- the retry recovers.

        assert controller.calls == 2
        assert match.current_players() == ["B"]

    def test_raises_agent_timeout_error_chained_from_the_second_exception_when_both_fail(
        self, counter_engine: CounterEngine
    ) -> None:
        exceptions = iter([RuntimeError("first failure"), RuntimeError("second failure")])
        controller = _AlwaysRaisingController(lambda: next(exceptions))
        seats = {"A": controller, "B": _FixedController(INC)}
        match: CounterMatch = Match(counter_engine, players=["A", "B"], seats=seats)
        before = match.serialize()

        with pytest.raises(AgentTimeoutError) as exc_info:
            match.play_turn()

        assert controller.calls == 2
        # Chained via `raise AgentTimeoutError(...) from exc` -- the second
        # (not first) attempt's exception, never lost.
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert str(exc_info.value.__cause__) == "second failure"
        # Nothing was ever submitted: state is completely unchanged and the
        # same player is still up, exactly like an uncaught IllegalActionError.
        assert match.serialize() == before
        assert match.current_players() == ["A"]

    def test_on_agent_error_hook_fires_for_each_failed_attempt_but_never_suppresses_the_error(
        self, counter_engine: CounterEngine
    ) -> None:
        exceptions = iter([RuntimeError("first failure"), RuntimeError("second failure")])
        controller = _AlwaysRaisingController(lambda: next(exceptions))
        seats = {"A": controller, "B": _FixedController(INC)}
        match: CounterMatch = Match(counter_engine, players=["A", "B"], seats=seats)

        calls: list[tuple[str, str]] = []
        with pytest.raises(AgentTimeoutError):
            match.play_turn(on_agent_error=lambda player, exc: calls.append((player, str(exc))))

        assert calls == [("A", "first failure"), ("A", "second failure")]


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
