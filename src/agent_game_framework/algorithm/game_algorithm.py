"""``GameAlgorithm`` Protocol and its ``AlgorithmRecommendation`` return type
(ADR-0004, SLICES.md V4 step 1).

An algorithm is a **third pillar**, independent of both ``GameEngine``
(ADR-0003, ``agent_game_framework.core.engine``) and ``SeatController``
(ADR-0005, ``agent_game_framework.core.seat_controller``). Per ADR-0004, it
must never be part of a game's own implementation -- not owned by it, not
shipped inside its package as "the" advisor -- but a standardized,
independently-authored component that plugs into *any* seat composition, for
*any* game, without that game's repo needing to know it exists. Concretely
this means a third-party developer can write an alternative algorithm for an
existing game (e.g. a better Catan heuristic) using only that game's public
``ObservationT``/``ActionT`` types, with zero access to or dependency on the
game's own rules code.

That "standardized tool, not part of a game's own implementation" framing is
also why this module carries **zero dependency on ``GameEngine``,
``SeatController``, or any specific game** -- not just as a design intent,
but literally: nothing in this module imports from
``agent_game_framework.core`` or ``agent_game_framework.agents``.
``ObservationT``/``ActionT`` below are ``GameAlgorithm``'s own generic type
parameters, structurally the same shape a ``GameEngine``/``SeatController``
implementation's types would be, but this module never imports those classes
to get them -- a future contributor must not "helpfully" import ``PlayerId``,
``GameEngine``, or a ``SeatController``/``SeatDecision`` type here just
because it looks convenient; doing so would silently reintroduce the exact
coupling ADR-0004 exists to prevent. Composition with a ``SeatController``
(auto-computing a recommendation every turn and either attaching it to an
LLM's context or using ``best_action`` directly as the move) happens entirely
in framework-provided ``SeatController`` implementations built *on top of*
this Protocol (``AdvisedLLMSeatController``, ``AutoplayNarratorSeatController``,
SLICES.md V4 steps 3-4) -- none of that composition logic lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AlgorithmRecommendation[ActionT]:
    """One algorithm's answer to a ``recommend()`` call: a mandatory best
    move plus optional, loosely-typed supporting detail.

    ``best_action`` is mandatory -- per ADR-0004, "this is what makes it
    usable as an actual move, not just advisory text": an
    ``AutoplayNarratorSeatController`` can use it directly as the seat's move
    with no further decision-making, and an ``AdvisedLLMSeatController`` can
    offer it to its inner LLM as a concrete suggestion, not merely
    commentary.

    ``rationale``/``scores`` are both optional and deliberately loosely
    typed -- shape left to each concrete algorithm. ``rationale`` is free
    text explaining the pick (e.g. for narration or an advised LLM's
    context); ``scores`` is a per-candidate-move scoring dict (e.g. a Catan
    heuristic might populate it across every candidate move, a poker solver
    might use it for equity/pot-odds numbers) -- an algorithm that has no use
    for one or both simply leaves them ``None``.

    Frozen so a returned recommendation can't be mutated after being handed
    to a caller (mirrors ``SeatDecision``'s frozen-ness in
    ``agent_game_framework.core.seat_controller`` -- the analogous
    house convention for a small, immutable "here's my answer" value).
    """

    best_action: ActionT
    rationale: str | None = None
    scores: dict[ActionT, float] | None = None


class GameAlgorithm[ObservationT, ActionT](Protocol):
    """The one contract every game-algorithm implementation satisfies
    (ADR-0004).

    ``ObservationT``/``ActionT`` are a game's already-public observation and
    action types (the same ones a ``GameEngine`` implementation for that game
    uses) -- a ``GameAlgorithm`` implementation touches nothing but these,
    never a game engine's internal state representation and never its rules
    code. That constraint is what makes it possible to write and test a
    ``GameAlgorithm`` for a given game entirely outside that game's own repo.

    Write one ``GameAlgorithm`` implementation and it can be dropped, without
    modification, into any composition mode a ``SeatController`` provides
    over it (LLM-advised, algorithm-autoplay-with-narration, or a bare
    algorithm-only bot) -- none of those composition modes are this
    Protocol's concern; it is a thin, single-method structural contract.
    """

    def recommend(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> AlgorithmRecommendation[ActionT]:
        """Recommend a move given the algorithm's current observation.

        ``legal_actions`` mirrors ``SeatController.decide``'s treatment of
        the same parameter: advisory input for the algorithm to reason
        over, not something this method must itself enforce -- whether an
        out-of-list ``best_action`` is ever produced, and what happens if it
        is, is a concern for whatever composes this recommendation into an
        actual seat decision (a ``SeatController`` implementation), not for
        this Protocol.
        """
        ...
