"""Unit tests for the ``SeatController`` Protocol and ``SeatDecision`` type
(KAN-1276, ADR-0005): no external calls, no subprocess.

``FirstLegalActionController`` below is a minimal, test-only ``SeatController``
that always returns the first legal action with no banter -- it exists only
to prove the Protocol's shape is usable structurally (no explicit
inheritance required); it is not a real controller implementation (those are
KAN-1278+, out of scope here).
"""

from __future__ import annotations

import dataclasses

import pytest

from agent_game_framework.core import SeatController, SeatDecision


class FirstLegalActionController:
    """Test-only ``SeatController``: always picks ``legal_actions[0]``."""

    def decide(self, observation: dict[str, object], legal_actions: list[str]) -> SeatDecision[str]:
        return SeatDecision(action=legal_actions[0])


def test_seat_decision_defaults_banter_to_none() -> None:
    decision = SeatDecision(action="inc")
    assert decision.action == "inc"
    assert decision.banter is None


def test_seat_decision_accepts_explicit_banter() -> None:
    decision = SeatDecision(action="inc", banter="taking my turn")
    assert decision.action == "inc"
    assert decision.banter == "taking my turn"


def test_seat_decision_is_frozen() -> None:
    decision = SeatDecision(action="inc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.action = "cheat"  # type: ignore[misc]


def test_fake_controller_satisfies_seat_controller_protocol() -> None:
    controller: SeatController[dict[str, object], str] = FirstLegalActionController()
    decision = controller.decide(observation={}, legal_actions=["inc", "dec"])

    assert isinstance(decision, SeatDecision)
    assert decision.action in ["inc", "dec"]
    assert decision.action == "inc"
    assert decision.banter is None
