"""``RandomBotController``: a uniform-random-move ``SeatController`` (ADR-0005,
KAN-1278).

A non-LLM, non-human ``SeatController`` implementation -- per ADR-0005,
"a random-move bot ... [is a] `SeatController` implementation too, with no
LLM involved at all." No special-casing versus ``HumanCLIController`` or any
future agent backend: it just picks uniformly at random from the
``legal_actions`` it is given.
"""

from __future__ import annotations

import random

from agent_game_framework.core.seat_controller import SeatDecision


class RandomBotController[ObservationT, ActionT]:
    """Picks uniformly at random among ``legal_actions`` (``SeatController``,
    ADR-0005).

    Accepts an optional ``random.Random`` instance so tests can inject a
    seeded generator for deterministic, reproducible bot play -- the global
    ``random`` module is never used directly. Defaults to a fresh
    ``random.Random()`` (unseeded) when not given.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng if rng is not None else random.Random()

    def decide(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> SeatDecision[ActionT]:
        """Return a uniformly random choice from ``legal_actions``, no banter."""
        return SeatDecision(action=self._rng.choice(legal_actions), banter=None)
