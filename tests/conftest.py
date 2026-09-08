"""Shared fixtures for exercising ``Match``'s orchestration logic.

``CounterEngine`` is a trivial, strict-turn-order, 2+-seat toy ``GameEngine``
used only to prove ``Match`` wires the contract together correctly (KAN-1275).
It is not a real game -- the actual reference implementation is Tic-Tac-Toe
(KAN-1277), built separately.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from agent_game_framework.core import IllegalActionError, Match, PlayerId

COUNTER_SCHEMA_VERSION = 1

INC = "inc"
"""The only legal action ``CounterEngine`` ever accepts."""


@dataclass
class CounterState:
    """State for the ``CounterEngine`` toy game."""

    players: list[PlayerId]
    turn_index: int
    scores: dict[PlayerId, int]
    target: int


class CounterEngine:
    """A strict-turn-order toy ``GameEngine``: players take turns submitting
    ``"inc"``, which adds 1 to the acting player's score. The first player to
    reach ``target`` (from ``config``, default 3) wins and the match ends.

    Exists purely as a ``GameEngine`` test double for ``Match`` tests -- see
    the module docstring.
    """

    def initial_state(self, players: list[PlayerId], config: dict[str, Any]) -> CounterState:
        return CounterState(
            players=list(players),
            turn_index=0,
            scores=dict.fromkeys(players, 0),
            target=int(config.get("target", 3)),
        )

    def current_players(self, state: CounterState) -> list[PlayerId]:
        if self.is_terminal(state):
            return []
        return [state.players[state.turn_index]]

    def legal_actions(self, state: CounterState, player: PlayerId) -> list[str]:
        if player not in self.current_players(state):
            return []
        return [INC]

    def apply_action(self, state: CounterState, player: PlayerId, action: str) -> CounterState:
        if player not in self.current_players(state):
            raise IllegalActionError(f"{player!r} may not act now")
        if action != INC:
            raise IllegalActionError(f"unknown action {action!r}")
        new_scores = dict(state.scores)
        new_scores[player] += 1
        return CounterState(
            players=list(state.players),
            turn_index=(state.turn_index + 1) % len(state.players),
            scores=new_scores,
            target=state.target,
        )

    def is_terminal(self, state: CounterState) -> bool:
        return any(score >= state.target for score in state.scores.values())

    def winners(self, state: CounterState) -> list[PlayerId]:
        return [p for p, score in state.scores.items() if score >= state.target]

    def observation_for(self, state: CounterState, player: PlayerId) -> dict[str, Any]:
        return {
            "you": player,
            "scores": dict(state.scores),
            "current_players": self.current_players(state),
        }

    def serialize(self, state: CounterState) -> dict[str, Any]:
        return {
            "schema_version": COUNTER_SCHEMA_VERSION,
            "players": list(state.players),
            "turn_index": state.turn_index,
            "scores": dict(state.scores),
            "target": state.target,
        }

    def deserialize(self, data: dict[str, Any]) -> CounterState:
        if data.get("schema_version") != COUNTER_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data.get('schema_version')!r}")
        return CounterState(
            players=list(data["players"]),
            turn_index=data["turn_index"],
            scores=dict(data["scores"]),
            target=data["target"],
        )


CounterMatch = Match[CounterState, str, dict[str, Any]]


@pytest.fixture
def counter_engine() -> CounterEngine:
    return CounterEngine()


@pytest.fixture
def make_match(counter_engine: CounterEngine) -> Callable[..., CounterMatch]:
    """Factory fixture: build a fresh ``Match`` over ``CounterEngine``."""

    def _make(players: list[PlayerId] | None = None, target: int = 3) -> CounterMatch:
        return Match(counter_engine, players or ["A", "B"], {"target": target})

    return _make
