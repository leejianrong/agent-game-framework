"""``AdvisedLLMSeatController``: an LLM ``SeatController`` advised by a
``GameAlgorithm`` recommendation it may follow or override (ADR-0004,
KAN-1290, SLICES.md V4 step 3).

Per ADR-0004, ``SeatController.decide(observation, legal_actions) ->
SeatDecision`` is a **fixed** contract -- "the core contract has no knowledge
of algorithms at all." There is no third "extra context" parameter to
``decide()`` for this class to add, and this module must not invent one.
Instead, composition happens the way ADR-0004 says it should: entirely
*inside* a specific ``SeatController`` implementation, built on top of the
standalone ``GameAlgorithm`` Protocol (``agent_game_framework.algorithm.game_algorithm``),
never by changing that Protocol or ``SeatController`` itself.

**The mechanism.** ``AdvisedLLMSeatController.decide`` calls
``algorithm.recommend(observation, legal_actions)`` exactly once, then
augments the *observation dict itself* with the recommendation under an
``"algorithm_recommendation"`` key before handing it to the inner ``llm``'s
own ``decide()`` call -- it never adds a parameter to ``decide()``'s
signature. This is a deliberate, scoped assumption (not a fully-generic-over-
any-``ObservationT`` solution, which isn't really achievable without
assuming *some* structure to augment): it requires observations to be
``dict[str, Any]``-shaped, which is true of every observation in this
codebase today (``TicTacToeEngine.observation_for`` returns exactly that
shape) -- see ``_augment_observation`` below for why the augmented value is
a plain JSON-safe dict, not the ``AlgorithmRecommendation`` dataclass
instance itself.

**Why this composes for free with ``OpenRouterBackend`` (KAN-1284), with
zero changes to that class.** ``OpenRouterBackend._build_request`` already
does ``json.dumps({"observation": observation, "legal_actions":
legal_actions}, default=str)`` -- whatever extra key this module adds to
``observation`` rides along automatically into the outgoing LLM request
body. Nothing in ``openrouter.py`` needs to special-case algorithm
recommendations at all; from ``OpenRouterBackend``'s point of view, the
recommendation is indistinguishable from any other observation field the
game engine happened to include. See
``tests/integration/test_advised_llm_seat_controller.py``'s
``test_advised_seat_recommendation_reaches_real_openrouter_request_body``
for a real, wired-together proof of this.

**What this class never does.** It never validates, overrides, or
second-guesses whatever ``SeatDecision`` the inner ``llm`` returns -- the
ticket is explicit that the LLM "may follow or override the
recommendation," and ``AdvisedLLMSeatController`` returns the inner
``llm``'s decision verbatim, unconditionally. All of the actual
decision-making stays inside ``llm``; this class's only job is
auto-computing the recommendation and attaching it to context.
"""

from __future__ import annotations

from typing import Any, cast

from agent_game_framework.algorithm.game_algorithm import AlgorithmRecommendation, GameAlgorithm
from agent_game_framework.core.seat_controller import SeatController, SeatDecision

_RECOMMENDATION_KEY = "algorithm_recommendation"


def _recommendation_to_dict(recommendation: AlgorithmRecommendation[Any]) -> dict[str, Any]:
    """Turn one ``AlgorithmRecommendation`` into a plain, JSON-safe dict that
    carries ``best_action``/``rationale``/``scores`` through **unmodified**
    -- per the ticket's own wording, none of the three fields is summarized,
    rounded, or dropped here.

    Deliberately a plain ``dict``, not the ``AlgorithmRecommendation``
    dataclass instance itself: the augmented observation ends up inside
    ``OpenRouterBackend._build_request``'s ``json.dumps(..., default=str)``
    call, and a dataclass instance would fall through that call's
    ``default=str`` fallback to an opaque ``repr()`` string (unreadable to
    the model, and not round-trippable) rather than a structured JSON
    object. A plain dict of already-JSON-safe values (``ActionT`` is a
    per-game action -- an ``int``/``str``/etc, per every concrete
    ``ActionT`` in this codebase today) serializes exactly as given, with no
    ``default=str`` fallback ever invoked for it.
    """
    return {
        "best_action": recommendation.best_action,
        "rationale": recommendation.rationale,
        "scores": recommendation.scores,
    }


class AdvisedLLMSeatController[ObservationT, ActionT]:
    """A ``SeatController`` that auto-computes a ``GameAlgorithm``
    recommendation every turn, attaches it to the inner LLM's context, and
    returns whatever action + banter the LLM ultimately decides on (ADR-0004,
    "Advised" mode).

    Construct with an inner ``llm`` (any ``SeatController`` -- in practice an
    ``OpenRouterBackend``, but this class never assumes that concrete type,
    only the ``SeatController`` Protocol) and an ``algorithm`` (any
    ``GameAlgorithm`` for the same ``ObservationT``/``ActionT`` pair -- in
    practice, e.g., ``examples.tictactoe.algorithm.TicTacToeMinimaxAlgorithm``).
    Both are stored as-is; this class does no validation of either beyond
    what their own Protocols already guarantee.

    Scoped to ``ObservationT`` being ``dict``-shaped (specifically
    ``dict[str, Any]``) -- see the module docstring's "the mechanism"
    section for why this is a deliberate assumption, not a generic solution,
    and why it holds for every observation in this codebase today.
    """

    def __init__(
        self,
        llm: SeatController[ObservationT, ActionT],
        algorithm: GameAlgorithm[ObservationT, ActionT],
    ) -> None:
        self._llm = llm
        self._algorithm = algorithm

    def decide(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> SeatDecision[ActionT]:
        """Compute one recommendation, attach it to the observation, and
        return the inner ``llm``'s decision verbatim.

        Exactly three steps, matching SLICES.md V4's integration test plan
        word for word:

        1. Call ``self._algorithm.recommend(observation, legal_actions)``
           -- exactly once per ``decide()`` call, never once per legal
           action (there is no loop over ``legal_actions`` here at all).
        2. Build an augmented observation: ``observation`` plus one extra
           ``"algorithm_recommendation"`` key carrying the recommendation's
           ``best_action``/``rationale``/``scores`` unmodified (see
           ``_recommendation_to_dict``). ``observation`` itself, and any
           dict a caller passed in, is never mutated in place -- a new dict
           is built via ``{**observation, ...}``.
        3. Call ``self._llm.decide(augmented_observation, legal_actions)``
           and return whatever ``SeatDecision`` it produces, unchanged --
           this method never inspects, validates, or overrides the inner
           ``llm``'s chosen action, whether or not it matches the
           recommendation's ``best_action``.
        """
        recommendation = self._algorithm.recommend(observation, legal_actions)

        # ObservationT is assumed dict-shaped (see class/module docstring) --
        # the two `cast`s below don't check anything at runtime, they only
        # tell the type checker about that assumption at the one place it's
        # made. `{**observation, ...}` never mutates the caller's dict.
        observation_dict = cast(dict[str, Any], observation)
        augmented_observation = cast(
            ObservationT,
            {**observation_dict, _RECOMMENDATION_KEY: _recommendation_to_dict(recommendation)},
        )

        return self._llm.decide(augmented_observation, legal_actions)
