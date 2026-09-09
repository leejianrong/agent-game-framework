"""Integration tests for ``AdvisedLLMSeatController`` (ADR-0004, KAN-1290,
SLICES.md V4 step 3, integration test plan bullet one).

Integration-level (not unit): these tests exercise real composition across
``agent_game_framework.algorithm``/``agent_game_framework.core`` boundaries
-- and the last test below wires a real ``OpenRouterBackend`` (mocked HTTP
transport, per CLAUDE.md's rule that any live-API test must mock the HTTP
call) together with a real ``TicTacToeMinimaxAlgorithm`` -- rather than
testing either in isolation with no external moving parts (that's
``tests/unit``'s job).

Three properties from the ticket, in order:

1. ``algorithm.recommend`` is called exactly once per ``decide()`` call, not
   once per legal action (a counting test-double algorithm, mirroring
   ``RandomBotController``'s/``Match``'s counting-fake style elsewhere in
   this repo, e.g. ``tests/unit/test_match.py``).
2. The recommendation reaches the inner LLM's ``decide()`` call unmodified
   -- a fake inner ``llm`` captures the exact observation dict it received.
3. The inner LLM may override the recommendation -- ``AdvisedLLMSeatController``
   never second-guesses whatever action the inner ``llm`` returns.

Plus one real, wired-together smoke test: a real ``TicTacToeMinimaxAlgorithm``
(KAN-1289) and a real ``OpenRouterBackend`` (KAN-1284) against a mocked
``httpx2`` transport, proving the recommendation reaches the actual outgoing
HTTP request body with zero changes to ``openrouter.py`` -- mirroring
``tests/integration/test_match_agent_errors.py``'s pattern for wiring a real
``OpenRouterBackend`` against ``httpx2.MockTransport``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

from agent_game_framework.agents import OpenRouterBackend
from agent_game_framework.algorithm import AdvisedLLMSeatController, AlgorithmRecommendation
from agent_game_framework.core import Conversable, SeatController, SeatDecision
from agent_game_framework.core.conversable import ConversationTurn, TextTurn
from examples.tictactoe.algorithm.minimax import TicTacToeMinimaxAlgorithm


class _CountingFakeAlgorithm:
    """Test-only ``GameAlgorithm`` that always recommends a fixed
    ``best_action`` and counts how many times ``recommend`` was called --
    the seam ``test_recommend_called_exactly_once_per_decide_call`` asserts
    against, mirroring ``RandomBotController``'s injectable-seam-for-tests
    style and ``tests/unit/test_match.py``'s controller-call-counting
    fakes."""

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


class _CapturingFakeLLM:
    """Test-only inner ``SeatController`` that records the exact
    ``observation`` dict it was called with, then returns a fixed
    ``SeatDecision`` -- lets a test assert on precisely what
    ``AdvisedLLMSeatController`` handed downstream, with no real LLM/HTTP
    call involved."""

    def __init__(self, action: str, banter: str | None = "noted") -> None:
        self._action = action
        self._banter = banter
        self.captured_observation: dict[str, Any] | None = None
        self.captured_legal_actions: list[str] | None = None

    def decide(
        self, observation: dict[str, Any], legal_actions: list[str]
    ) -> SeatDecision[str]:
        self.captured_observation = observation
        self.captured_legal_actions = legal_actions
        return SeatDecision(action=self._action, banter=self._banter)

    def respond(self, history: list[ConversationTurn], incoming: TextTurn) -> TextTurn:
        return TextTurn(text=f"echo: {incoming.text}")


class _NonConversableFakeLLM:
    """Test-only inner ``SeatController`` that deliberately has no
    ``respond()`` at all -- used to prove ``AdvisedLLMSeatController.respond``
    raises a clear ``TypeError`` rather than an ``AttributeError`` when its
    inner ``llm`` isn't itself ``Conversable``."""

    def decide(self, observation: dict[str, Any], legal_actions: list[str]) -> SeatDecision[str]:
        return SeatDecision(action=legal_actions[0])


def test_recommend_called_exactly_once_per_decide_call_not_once_per_legal_action() -> None:
    """``AdvisedLLMSeatController.decide`` calls ``algorithm.recommend``
    exactly once per ``decide()`` call, regardless of how many legal
    actions are on offer -- not once per legal action (SLICES.md V4
    integration test plan, first bullet, verbatim)."""
    algorithm = _CountingFakeAlgorithm(best_action="b", rationale="pick b", scores={"a": 0.1})
    llm = _CapturingFakeLLM(action="b")
    controller: SeatController[dict[str, Any], str] = AdvisedLLMSeatController(
        llm=llm, algorithm=algorithm
    )

    legal_actions = ["a", "b", "c", "d", "e"]  # five legal actions, one decide() call.
    controller.decide(observation={"turn": 1}, legal_actions=legal_actions)

    assert algorithm.call_count == 1


def test_recommendation_passed_through_to_inner_llm_unmodified() -> None:
    """The augmented observation handed to the inner ``llm`` contains the
    algorithm's ``best_action``/``rationale``/``scores`` byte-for-byte --
    not summarized, rounded, or altered (SLICES.md V4 integration test
    plan, "passes it through to the inner LLM unmodified")."""
    scores = {"a": -1.0, "b": 1.0, "c": 0.0}
    algorithm = _CountingFakeAlgorithm(
        best_action="b", rationale="cell b wins outright", scores=scores
    )
    llm = _CapturingFakeLLM(action="b")
    controller: SeatController[dict[str, Any], str] = AdvisedLLMSeatController(
        llm=llm, algorithm=algorithm
    )

    original_observation = {"turn": 3, "board": ["a", None, None]}
    controller.decide(observation=original_observation, legal_actions=["a", "b", "c"])

    assert llm.captured_observation is not None
    recommendation_payload = llm.captured_observation["algorithm_recommendation"]
    assert recommendation_payload["best_action"] == "b"
    assert recommendation_payload["rationale"] == "cell b wins outright"
    assert recommendation_payload["scores"] == scores
    # The rest of the original observation still rides along, unmodified.
    assert llm.captured_observation["turn"] == 3
    assert llm.captured_observation["board"] == ["a", None, None]
    # The caller's own observation dict was never mutated in place.
    assert original_observation == {"turn": 3, "board": ["a", None, None]}


def test_llm_may_override_the_recommendation() -> None:
    """When the inner ``llm`` returns a different action than the
    algorithm's ``best_action``, ``AdvisedLLMSeatController.decide()``
    returns that overriding action verbatim -- this class never second-
    guesses or overrides the inner ``llm``'s own decision (ADR-0004: "it may
    follow or override the recommendation")."""
    algorithm = _CountingFakeAlgorithm(best_action="a", rationale="a is best", scores={"a": 1.0})
    llm = _CapturingFakeLLM(action="c", banter="I know better")  # deliberately overrides "a".
    controller: SeatController[dict[str, Any], str] = AdvisedLLMSeatController(
        llm=llm, algorithm=algorithm
    )

    decision = controller.decide(observation={}, legal_actions=["a", "b", "c"])

    assert decision.action == "c"
    assert decision.banter == "I know better"


def test_advised_seat_recommendation_reaches_real_openrouter_request_body() -> None:
    """Strongest proof this composes for free with zero changes to
    ``OpenRouterBackend``: a real ``TicTacToeMinimaxAlgorithm`` (KAN-1289)
    wired into a real ``AdvisedLLMSeatController`` around a real
    ``OpenRouterBackend`` (KAN-1284), HTTP mocked via
    ``httpx2.MockTransport`` (mirroring
    ``tests/integration/test_match_agent_errors.py``'s ``_client_returning``
    pattern). The outgoing chat-completions request body -- parsed the same
    way ``tests/e2e/_mock_openrouter_server.py`` inspects request shape --
    must actually contain the minimax recommendation's exact
    ``best_action``.
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
    llm = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)
    algorithm = TicTacToeMinimaxAlgorithm()
    controller: SeatController[dict[str, Any], int] = AdvisedLLMSeatController(
        llm=llm, algorithm=algorithm
    )

    # Empty Tic-Tac-Toe board, X to move -- minimax's best_action for an
    # empty board is cell 0 (its lowest-index-tie-break rule; see
    # examples/tictactoe/algorithm/minimax.py's module docstring).
    observation = {"you": "X", "board": [None] * 9}
    legal_actions = list(range(9))
    expected_recommendation = algorithm.recommend(observation, legal_actions)

    decision = controller.decide(observation=observation, legal_actions=legal_actions)

    assert decision.action == 4  # the LLM's mocked response, returned verbatim.
    assert len(captured_requests) == 1
    user_message = next(
        m["content"] for m in captured_requests[0]["messages"] if m["role"] == "user"
    )
    sent_observation = json.loads(user_message)["observation"]
    sent_recommendation = sent_observation["algorithm_recommendation"]
    assert sent_recommendation["best_action"] == expected_recommendation.best_action
    assert sent_recommendation["rationale"] == expected_recommendation.rationale
    expected_scores = expected_recommendation.scores
    assert expected_scores is not None
    # scores keys arrive as JSON strings (JSON object keys are always
    # strings) -- compare against the same stringified form rather than the
    # int-keyed dict the algorithm itself produced.
    assert sent_recommendation["scores"] == {str(k): v for k, v in expected_scores.items()}


def test_respond_delegates_to_the_inner_llm_unconditionally() -> None:
    """``AdvisedLLMSeatController.respond`` (ADR-0008/ADR-0009) is a pure
    pass-through to the inner ``llm`` -- chat has nothing to do with the
    algorithm at all, unlike ``decide()``."""
    llm = _CapturingFakeLLM(action="b")
    algorithm = _CountingFakeAlgorithm(best_action="b", rationale="pick b", scores={"a": 0.1})
    controller = AdvisedLLMSeatController(llm=llm, algorithm=algorithm)
    assert isinstance(controller, Conversable)

    output = controller.respond(history=[], incoming=TextTurn(text="hello"))

    assert output == TextTurn(text="echo: hello")
    # Chatting never consults the algorithm at all.
    assert algorithm.call_count == 0


def test_respond_raises_type_error_when_inner_llm_is_not_conversable() -> None:
    """``isinstance(controller, Conversable)`` is always ``True`` for this
    class -- it always defines ``respond()`` itself, structurally satisfying
    the ``@runtime_checkable`` Protocol regardless of the inner ``llm`` -- so
    the actual guarantee this test proves is that *calling* ``respond()``
    fails clearly (``TypeError``, naming the culprit) rather than silently
    or with a bare ``AttributeError``, when that inner ``llm`` turns out not
    to support chat itself."""
    llm = _NonConversableFakeLLM()
    algorithm = _CountingFakeAlgorithm(best_action="b", rationale="pick b", scores={"a": 0.1})
    controller = AdvisedLLMSeatController(llm=llm, algorithm=algorithm)

    with pytest.raises(TypeError):
        controller.respond(history=[], incoming=TextTurn(text="hello"))
