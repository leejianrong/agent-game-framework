"""``SeatController`` Protocol and its ``SeatDecision`` return type (ADR-0005,
PLAN.md Shape S3).

Every seat in a ``Match`` -- human, algorithmic bot, or LLM-backed agent -- is
filled by an implementation of one Protocol, ``SeatController``. This module
carries **no game-algorithm knowledge at all**: a ``GameAlgorithm`` (ADR-0004)
is never a parameter of ``decide()``. Any composition of an LLM with an
algorithm (advised play, or algorithm-plays-while-LLM-narrates) happens
entirely inside a specific ``SeatController`` implementation (future V4
work), invisible at this Protocol's boundary. ``SeatController`` itself does
not validate ``decide()``'s result against ``legal_actions`` -- that
enforcement point is ``Match.submit_action``/``GameEngine.apply_action`` (see
``agent_game_framework.core.match``), which raises ``IllegalActionError`` for
every controller kind identically. This module stays a thin structural
contract, not a validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SeatDecision[ActionT]:
    """One seat's response to a ``decide()`` call: a legal action plus an
    optional short free-text banter string.

    ``banter`` defaults to ``None`` -- most controllers (a random bot, a bare
    algorithm) never produce any; only an LLM-backed or human controller
    typically sets it. Frozen so a returned decision can't be mutated after
    ``Match`` has seen it.
    """

    action: ActionT
    banter: str | None = None


class SeatController[ObservationT, ActionT](Protocol):
    """The one contract every seat-filling implementation satisfies (ADR-0005).

    ``ObservationT``/``ActionT`` are the same type parameters a game's
    ``GameEngine`` implementation uses (see
    ``agent_game_framework.core.engine.GameEngine``), so a ``SeatController``
    for a given game's observation/action types is unambiguous.

    A human player (``HumanCLIController``), a random-move bot
    (``RandomBotController``), a bare algorithm (``AlgorithmSeatController``,
    ADR-0004), and an LLM-backed ``AgentBackend`` (``OpenRouterBackend``,
    future V3) are all just ``SeatController`` implementations -- none of
    those concrete controllers live in this module; this is the structural
    contract they all satisfy.
    """

    def decide(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> SeatDecision[ActionT]:
        """Choose an action given the seat's current observation.

        ``legal_actions`` is advisory input, not something ``decide()`` must
        itself enforce -- an out-of-list or malformed result is rejected
        downstream by ``Match``/``GameEngine.apply_action`` via
        ``IllegalActionError``, identically regardless of controller kind.
        """
        ...
