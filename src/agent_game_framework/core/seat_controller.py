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

This module also carries ``AgentTimeoutError`` (SLICES.md V3 step 2,
KAN-1285): the failure mode of a ``decide()`` call that raises instead of
returning, as opposed to one that returns a well-formed-but-illegal
``SeatDecision`` (that's ``IllegalActionError``'s territory, over in
``core.engine``). See its own docstring for why it lives here.
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


class AgentTimeoutError(Exception):
    """Raised when a ``SeatController`` fails to produce a decision at all,
    after ``Match`` has already given it one immediate retry (SLICES.md V3
    step 2, KAN-1285).

    This pairs with ``IllegalActionError``
    (``agent_game_framework.core.engine``) the same way this module's
    ``SeatController`` pairs with ``GameEngine``: ``IllegalActionError``
    signals "the engine's legality contract was violated" (a well-formed
    action that isn't allowed); ``AgentTimeoutError`` signals "the
    controller-contract itself was violated" (no decision was produced at
    all -- a raised exception instead of a returned ``SeatDecision``, e.g. a
    network timeout or an unparseable API response). It belongs here, next
    to ``SeatController``, rather than next to ``GameEngine``, because it has
    nothing to do with game rules -- an engine never sees a controller that
    failed to decide; ``Match`` catches the failure before ``submit_action``
    is ever called.

    Raised by ``Match.play_turn`` -- see its docstring for the exact
    reject-and-reprompt-once policy -- with the second, still-failing
    attempt's exception chained on as ``__cause__`` (``raise
    AgentTimeoutError(...) from exc``), so the original failure (a real
    ``httpx2`` timeout, an ``OpenRouterBackend.ResponseParseError``, or
    anything else a ``SeatController.decide()`` implementation might raise)
    is never lost, only wrapped. ``Match``/``core`` never import or reference
    any specific controller's exception types by name (``core`` must never
    import from ``agents`` -- see ``Match.play_turn``'s module docstring) --
    catching is done via a broad ``except Exception``, deliberately
    controller-implementation-agnostic, per ADR-0005's requirement that a
    seat's failure is never handled differently because of which concrete
    ``SeatController`` happens to be behind it.
    """


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
