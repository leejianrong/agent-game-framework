"""Unit tests for the ``Match`` orchestrator (KAN-1275, ADR-0003): no
external calls, no subprocess. Exercises ``Match`` against the
``CounterEngine`` fake defined in ``tests/conftest.py``, one behavior at a
time.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from agent_game_framework.core import IllegalActionError, Match

if TYPE_CHECKING:
    from conftest import CounterEngine, CounterMatch

INC = "inc"


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
