"""Integration tests for ``AutoplayNarratorSeatController`` (ADR-0004,
KAN-1292, SLICES.md V4 step 4, integration test plan bullet two).

Integration-level (not unit): these tests exercise real composition across
``agent_game_framework.algorithm``/``agent_game_framework.core`` boundaries
-- and the last test below wires a real ``OpenRouterBackend`` (mocked HTTP
transport, per CLAUDE.md's rule that any live-API test must mock the HTTP
call) together with a real ``TicTacToeMinimaxAlgorithm`` -- mirroring
``tests/integration/test_advised_llm_seat_controller.py``'s structure and
test-double style, applied to this controller's opposite composition rule:
the algorithm decides, the narrator never does.

Properties asserted, in order (SLICES.md V4 integration test plan, second
bullet, plus the ticket's own wording):

1. ``algorithm.recommend`` is called exactly once per ``decide()`` call, not
   once per legal action (a counting test-double algorithm, reused from the
   same style as ``test_advised_llm_seat_controller.py``'s
   ``_CountingFakeAlgorithm``).
2. The final ``SeatDecision.action`` always equals ``recommendation.best_action``
   exactly -- including when a deliberately-misbehaving fake ``narrator_llm``
   returns some *other* action despite being given a 1-element
   ``legal_actions`` list, proving this controller truly ignores whatever
   action the narrator returns rather than merely relying on the 1-element
   constraint to make misbehavior impossible.
3. The narrator's ``decide()`` call receives ``legal_actions == [best_action]``
   -- a single-element list -- asserted directly via a capturing fake.
4. The narrator's ``decide()`` call receives an observation carrying the
   chosen action + rationale, byte-for-byte, mirroring KAN-1290's
   "unmodified" test.
5. The final ``SeatDecision.banter`` is exactly whatever the narrator
   returned, unchanged.

Plus one real, wired-together smoke test: a real ``TicTacToeMinimaxAlgorithm``
(KAN-1289) and a real ``OpenRouterBackend`` (KAN-1284) against a mocked
``httpx2`` transport, proving (a) the outgoing tool schema constrains
``action`` to a 1-element ``enum`` matching the algorithm's ``best_action``,
and (b) even a mocked response that returns some other action is ignored --
the final decision's action is still the algorithm's ``best_action``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2

from agent_game_framework.agents import OpenRouterBackend
from agent_game_framework.algorithm import AlgorithmRecommendation, AutoplayNarratorSeatController
from agent_game_framework.core import SeatController, SeatDecision
from examples.tictactoe.algorithm.minimax import TicTacToeMinimaxAlgorithm


class _CountingFakeAlgorithm:
    """Test-only ``GameAlgorithm`` that always recommends a fixed
    ``best_action`` and counts how many times ``recommend`` was called --
    mirrors ``test_advised_llm_seat_controller.py``'s
    ``_CountingFakeAlgorithm`` exactly."""

    def __init__(self, best_action: str, rationale: str, scores: dict[str, float]) -> None:
        self._recommendation = AlgorithmRecommendation(
            best_action=best_action, rationale=rationale, scores=scores
        )
        self.call_count = 0

    def recommend(
        self, observation: dict[str, Any], legal_actions: list[str]
    ) -> AlgorithmRecommendation[str]:
        self.call_count += 1
        return self._recommendation


class _CapturingFakeNarrator:
    """Test-only ``narrator_llm`` that records the exact ``observation`` and
    ``legal_actions`` it was called with, then returns a fixed
    ``SeatDecision`` -- lets a test assert on precisely what
    ``AutoplayNarratorSeatController`` handed downstream, with no real LLM/
    HTTP call involved.

    ``action`` defaults to a sentinel *different* from any real algorithm
    action so that a test which forgets to override it would fail loudly if
    the controller ever accidentally let this value leak into the final
    decision -- but the misbehavior test below sets it explicitly anyway,
    to make the intent unambiguous at the call site.
    """

    def __init__(
        self, action: str = "__narrator_should_never_pick_this__", banter: str | None = "noted"
    ) -> None:
        self._action = action
        self._banter = banter
        self.captured_observation: dict[str, Any] | None = None
        self.captured_legal_actions: list[str] | None = None

    def decide(self, observation: dict[str, Any], legal_actions: list[str]) -> SeatDecision[str]:
        self.captured_observation = observation
        self.captured_legal_actions = legal_actions
        return SeatDecision(action=self._action, banter=self._banter)


def test_recommend_called_exactly_once_per_decide_call_not_once_per_legal_action() -> None:
    """``AutoplayNarratorSeatController.decide`` calls ``algorithm.recommend``
    exactly once per ``decide()`` call, regardless of how many legal actions
    are on offer -- not once per legal action."""
    algorithm = _CountingFakeAlgorithm(best_action="b", rationale="pick b", scores={"a": 0.1})
    narrator = _CapturingFakeNarrator(action="b")
    controller: SeatController[dict[str, Any], str] = AutoplayNarratorSeatController(
        algorithm=algorithm, narrator_llm=narrator
    )

    legal_actions = ["a", "b", "c", "d", "e"]  # five legal actions, one decide() call.
    controller.decide(observation={"turn": 1}, legal_actions=legal_actions)

    assert algorithm.call_count == 1


def test_final_action_ignores_narrator_even_when_it_returns_a_different_action() -> None:
    """The strongest guarantee this ticket asks for: even a deliberately-
    misbehaving ``narrator_llm`` that returns an action other than
    ``best_action`` (despite being given a 1-element ``legal_actions``) has
    zero effect on the final decision -- ``AutoplayNarratorSeatController``
    never reads ``narrator_decision.action`` at all."""
    algorithm = _CountingFakeAlgorithm(best_action="a", rationale="a is best", scores={"a": 1.0})
    narrator = _CapturingFakeNarrator(
        action="z", banter="I'll pick z instead!"
    )  # malicious/misbehaving.
    controller: SeatController[dict[str, Any], str] = AutoplayNarratorSeatController(
        algorithm=algorithm, narrator_llm=narrator
    )

    decision = controller.decide(observation={}, legal_actions=["a", "b", "c"])

    assert decision.action == "a"  # algorithm's best_action, not the narrator's "z".
    assert decision.banter == "I'll pick z instead!"  # banter still passes through unchanged.


def test_narrator_receives_single_element_legal_actions() -> None:
    """The narrator's ``decide()`` call receives ``legal_actions ==
    [best_action]`` -- a single-element list, so the narrator has no real
    choice to make even before the defense-in-depth guarantee kicks in."""
    algorithm = _CountingFakeAlgorithm(
        best_action="b", rationale="pick b", scores={"a": 0.1, "b": 1.0}
    )
    narrator = _CapturingFakeNarrator(action="b")
    controller: SeatController[dict[str, Any], str] = AutoplayNarratorSeatController(
        algorithm=algorithm, narrator_llm=narrator
    )

    controller.decide(observation={"turn": 1}, legal_actions=["a", "b", "c", "d"])

    assert narrator.captured_legal_actions == ["b"]


def test_narrator_receives_chosen_action_and_rationale_unmodified() -> None:
    """The augmented observation handed to the narrator contains the
    algorithm's chosen action + rationale byte-for-byte -- not summarized,
    rounded, or altered -- and never the ``scores`` dict (SLICES.md V4's
    ticket wording is narrower than ``AdvisedLLMSeatController``'s: "chosen
    action + rationale" only)."""
    algorithm = _CountingFakeAlgorithm(
        best_action="b", rationale="cell b wins outright", scores={"a": -1.0, "b": 1.0, "c": 0.0}
    )
    narrator = _CapturingFakeNarrator(action="b")
    controller: SeatController[dict[str, Any], str] = AutoplayNarratorSeatController(
        algorithm=algorithm, narrator_llm=narrator
    )

    original_observation = {"turn": 3, "board": ["a", None, None]}
    controller.decide(observation=original_observation, legal_actions=["a", "b", "c"])

    assert narrator.captured_observation is not None
    narrated_payload = narrator.captured_observation["narrated_decision"]
    assert narrated_payload["chosen_action"] == "b"
    assert narrated_payload["rationale"] == "cell b wins outright"
    assert "scores" not in narrated_payload
    # The rest of the original observation still rides along, unmodified.
    assert narrator.captured_observation["turn"] == 3
    assert narrator.captured_observation["board"] == ["a", None, None]
    # The caller's own observation dict was never mutated in place.
    assert original_observation == {"turn": 3, "board": ["a", None, None]}


def test_final_banter_passes_through_from_narrator_unchanged() -> None:
    """``SeatDecision.banter`` on the final decision is exactly whatever the
    narrator returned, unchanged."""
    algorithm = _CountingFakeAlgorithm(best_action="a", rationale="a is best", scores={"a": 1.0})
    narrator = _CapturingFakeNarrator(action="a", banter="a solid, if boring, choice")
    controller: SeatController[dict[str, Any], str] = AutoplayNarratorSeatController(
        algorithm=algorithm, narrator_llm=narrator
    )

    decision = controller.decide(observation={}, legal_actions=["a", "b"])

    assert decision.banter == "a solid, if boring, choice"


def test_autoplay_narrator_reaches_real_openrouter_request_body_and_ignores_its_response() -> None:
    """Strongest proof this composes for free with zero changes to
    ``OpenRouterBackend``, wired end to end: a real
    ``TicTacToeMinimaxAlgorithm`` (KAN-1289) inside a real
    ``AutoplayNarratorSeatController`` around a real ``OpenRouterBackend``
    (KAN-1284), HTTP mocked via ``httpx2.MockTransport`` (mirroring
    ``tests/integration/test_advised_llm_seat_controller.py``'s equivalent
    smoke test).

    Two assertions:

    (a) The outgoing chat-completions request's tool schema constrains
        ``action`` to a 1-element ``enum`` matching the algorithm's
        ``best_action`` exactly.
    (b) The mocked response is scripted to return a *different* action (cell
        4) than the algorithm's ``best_action`` (cell 0, for an empty board,
        per the minimax module's lowest-index tie-break) -- simulating a
        model that ignores or misreads the 1-element constraint. The final
        ``SeatDecision.action`` is still the algorithm's ``best_action``, not
        the mocked response's action.
    """
    captured_requests: list[dict[str, Any]] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        captured_requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "submit_move",
                                        "arguments": json.dumps(
                                            # Deliberately a *different* action
                                            # (4) than the algorithm's
                                            # best_action (0) -- simulates a
                                            # model ignoring/misreading the
                                            # 1-element enum constraint.
                                            {"action": 4, "banter": "taking the center"}
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    client = httpx2.Client(
        base_url="https://openrouter.ai/api/v1", transport=httpx2.MockTransport(_handler)
    )
    narrator_llm = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)
    algorithm = TicTacToeMinimaxAlgorithm()
    controller: SeatController[dict[str, Any], int] = AutoplayNarratorSeatController(
        algorithm=algorithm, narrator_llm=narrator_llm
    )

    # Empty Tic-Tac-Toe board, X to move -- minimax's best_action for an
    # empty board is cell 0 (its lowest-index-tie-break rule; see
    # examples/tictactoe/algorithm/minimax.py's module docstring).
    observation = {"you": "X", "board": [None] * 9}
    legal_actions = list(range(9))
    expected_recommendation = algorithm.recommend(observation, legal_actions)
    assert expected_recommendation.best_action == 0

    decision = controller.decide(observation=observation, legal_actions=legal_actions)

    # (b) The final action is the algorithm's best_action, never the mocked
    # response's "4", proving the narrator's own reply is fully ignored.
    assert decision.action == 0
    assert decision.banter == "taking the center"

    # (a) The outgoing request's tool schema constrains `action` to a
    # 1-element enum equal to the algorithm's best_action.
    assert len(captured_requests) == 1
    tool = captured_requests[0]["tools"][0]
    action_schema = tool["function"]["parameters"]["properties"]["action"]
    assert action_schema["enum"] == [0]
