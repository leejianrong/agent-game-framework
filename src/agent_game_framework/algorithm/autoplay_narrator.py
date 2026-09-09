"""``AutoplayNarratorSeatController``: a ``SeatController`` whose move is
always an algorithm's ``best_action``, narrated (never chosen) by an LLM
(ADR-0004, KAN-1292, SLICES.md V4 step 4).

Per ADR-0004, ``SeatController.decide(observation, legal_actions) ->
SeatDecision`` is a **fixed** contract -- exactly like
``AdvisedLLMSeatController`` (KAN-1290, ``advised_llm.py``), this module adds
no third parameter to ``decide()`` and invents no new Protocol. It is
``AdvisedLLMSeatController``'s sibling, built the same way -- auto-compute a
``GameAlgorithm`` recommendation every turn, augment the observation dict
handed to an inner ``SeatController`` -- but with the **opposite** answer to
"who picks the move":

- ``AdvisedLLMSeatController(llm, algorithm)``: the inner LLM decides; it may
  follow or override the recommendation. The algorithm is *advisory*.
- ``AutoplayNarratorSeatController(algorithm, narrator_llm)`` (this class):
  the algorithm decides, unconditionally; the inner ``narrator_llm`` is never
  asked to choose anything and supplies banter only. The algorithm is
  *authoritative*.

Note the constructor's parameter order is also reversed relative to
``AdvisedLLMSeatController`` -- ``(algorithm, narrator_llm)``, not
``(narrator_llm, algorithm)`` -- matching the ticket's own name,
``AutoplayNarratorSeatController(algorithm, narrator_llm)`` verbatim, since a
future CLI-wiring ticket (KAN-1291) may construct these positionally.

**Two independent guarantees that the narrator never picks the move**, per
the ticket's own wording ("the returned ``SeatDecision.action`` always
equals ``recommendation.best_action`` exactly, regardless of what the
narrator LLM's text output contains"):

1. **Structural constraint on the request.** ``self._narrator_llm.decide(...)``
   is called with ``legal_actions=[recommendation.best_action]`` -- a
   single-element list. For a real ``OpenRouterBackend`` (KAN-1284), this
   rides straight into ``_build_request``'s tool schema as
   ``"enum": legal_actions``, so the model's forced ``submit_move`` tool call
   is constrained to a JSON-schema ``enum`` with exactly one member --
   structurally, it cannot select any other action, the same way a
   single-candidate multiple-choice question has only one box to check.
2. **Defense in depth: the returned action is hardcoded, never read off the
   narrator's decision.** Guarantee 1 constrains a *well-behaved* model/
   ``SeatController``, but this class does not merely trust that constraint
   to hold -- it never even inspects ``narrator_decision.action``. The
   ``SeatDecision`` this method returns is built as
   ``SeatDecision(action=recommendation.best_action, banter=narrator_decision.banter)``,
   sourcing ``action`` directly from the algorithm's own recommendation. This
   is deliberately redundant with guarantee 1, not merely relying on it: a
   misbehaving or malicious test double (or a future narrator backend with a
   looser schema) could return some other ``.action`` value despite being
   given a 1-element ``legal_actions``, and this class would still ignore it
   completely. See
   ``tests/integration/test_autoplay_narrator_seat_controller.py``'s
   ``test_final_action_ignores_narrator_even_when_it_returns_a_different_action``
   for the exact scenario this guards against.

**What the narrator is told.** Per the ticket's exact wording -- "the
narrator LLM is given the observation + chosen action + rationale" -- this
is narrower than ``AdvisedLLMSeatController``'s full recommendation (which
also carries ``scores``, since an advised LLM is weighing candidate moves).
A narrator has nothing to weigh -- the decision already happened -- so only
``chosen_action``/``rationale`` are attached, under one
``"narrated_decision"`` key (mirroring ``AdvisedLLMSeatController``'s
``"algorithm_recommendation"`` key convention), never the ``scores`` dict.
Scoped to ``ObservationT`` being ``dict``-shaped (specifically
``dict[str, Any]``) for the same reason as ``AdvisedLLMSeatController`` --
see that module's docstring for why this is a deliberate, scoped assumption
rather than a fully-generic solution, and why it holds for every observation
in this codebase today.
"""

from __future__ import annotations

from typing import Any, cast

from agent_game_framework.algorithm.game_algorithm import GameAlgorithm
from agent_game_framework.core.conversable import (
    Conversable,
    ConversationInput,
    ConversationOutput,
    ConversationTurn,
)
from agent_game_framework.core.seat_controller import SeatController, SeatDecision

_NARRATION_KEY = "narrated_decision"


class AutoplayNarratorSeatController[ObservationT, ActionT]:
    """A ``SeatController`` that auto-computes a ``GameAlgorithm``
    recommendation every turn and uses its ``best_action`` **directly** as
    the seat's move -- the inner ``narrator_llm`` never picks the action,
    only produces banter about the move that already happened (ADR-0004,
    "Autoplay-narrated" mode).

    Construct with an ``algorithm`` (any ``GameAlgorithm`` for the same
    ``ObservationT``/``ActionT`` pair -- in practice, e.g.,
    ``examples.tictactoe.algorithm.TicTacToeMinimaxAlgorithm``) and a
    ``narrator_llm`` (any ``SeatController`` -- in practice an
    ``OpenRouterBackend``, but this class never assumes that concrete type,
    only the ``SeatController`` Protocol). Note the parameter order:
    ``algorithm`` first, ``narrator_llm`` second -- the opposite of
    ``AdvisedLLMSeatController(llm, algorithm)`` -- matching this class's own
    name in the ticket. Both are stored as-is; this class does no validation
    of either beyond what their own Protocols already guarantee.
    """

    def __init__(
        self,
        algorithm: GameAlgorithm[ObservationT, ActionT],
        narrator_llm: SeatController[ObservationT, ActionT],
    ) -> None:
        self._algorithm = algorithm
        self._narrator_llm = narrator_llm

    def decide(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> SeatDecision[ActionT]:
        """Compute one recommendation, let the algorithm's ``best_action``
        become the move unconditionally, and ask the narrator only for
        banter about it.

        Exactly four steps, matching this module's docstring and SLICES.md
        V4's integration test plan word for word:

        1. Call ``self._algorithm.recommend(observation, legal_actions)`` --
           exactly once per ``decide()`` call, never once per legal action.
        2. Build an augmented observation: ``observation`` plus one extra
           ``"narrated_decision"`` key carrying the recommendation's
           ``best_action``/``rationale`` (never ``scores`` -- see the module
           docstring for why). ``observation`` itself, and any dict a caller
           passed in, is never mutated in place -- a new dict is built via
           ``{**observation, ...}``.
        3. Call ``self._narrator_llm.decide(augmented_observation,
           [recommendation.best_action])`` -- a single-element
           ``legal_actions`` list, so the narrator has no real action to
           choose even if it tried (see the module docstring's guarantee 1).
        4. Return ``SeatDecision(action=recommendation.best_action,
           banter=narrator_decision.banter)`` -- ``action`` is sourced
           directly from the algorithm's recommendation, never from
           ``narrator_decision.action``, which is never even read (see the
           module docstring's guarantee 2). ``banter`` is passed through from
           the narrator's decision unchanged.
        """
        recommendation = self._algorithm.recommend(observation, legal_actions)

        # ObservationT is assumed dict-shaped (see class/module docstring) --
        # the two `cast`s below don't check anything at runtime, they only
        # tell the type checker about that assumption at the one place it's
        # made. `{**observation, ...}` never mutates the caller's dict.
        observation_dict = cast(dict[str, Any], observation)
        narrated_decision_payload = {
            "chosen_action": recommendation.best_action,
            "rationale": recommendation.rationale,
        }
        augmented_observation = cast(
            ObservationT,
            {**observation_dict, _NARRATION_KEY: narrated_decision_payload},
        )

        narrator_decision = self._narrator_llm.decide(
            augmented_observation, [recommendation.best_action]
        )

        # Guarantee 2 (defense in depth): `narrator_decision.action` is never
        # read here, by design -- the final action always comes from the
        # algorithm's own recommendation, regardless of what the narrator
        # returned.
        return SeatDecision(action=recommendation.best_action, banter=narrator_decision.banter)

    def respond(
        self, history: list[ConversationTurn], incoming: ConversationInput
    ) -> ConversationOutput:
        """``Conversable.respond`` (ADR-0008/ADR-0009) pass-through to the
        inner ``narrator_llm``: this seat's *moves* always come from
        ``algorithm`` unconditionally (see this class's own docstring), but
        chat is a separate capability entirely -- a human converses with the
        narrator itself, exactly as if it were a bare ``llm`` seat. Raises
        ``TypeError`` if ``narrator_llm`` doesn't itself implement
        ``Conversable`` (in this codebase, always an ``OpenRouterBackend`` in
        practice, which does)."""
        if not isinstance(self._narrator_llm, Conversable):
            raise TypeError(
                f"{type(self._narrator_llm).__name__} does not implement Conversable; "
                "this seat cannot be chatted with"
            )
        return self._narrator_llm.respond(history, incoming)
