"""End-to-end tests for the ``--seat ...:advised-by=...``/``...:narrated-by=...``
CLI seat modifiers driven through the real, installed ``agf`` console script
(KAN-1291, ADR-0004, SLICES.md V4 step 5 + full V4 test plan). This is the
last card in epic V4 -- merging it closes the epic and the entire
``agent-games`` Pandan board.

Like ``tests/e2e/test_cli_llm_seat.py`` (KAN-1287), these drive ``agf`` as a
real subprocess, set ``PYTHONPATH`` to the repo root so the subprocess can
import ``examples.tictactoe``/``examples.tictactoe.algorithm`` (ADR-0001),
and stand in for the real OpenRouter endpoint with
``tests/e2e/_mock_openrouter_server.py``'s ``MockOpenRouterServer`` via the
``OPENROUTER_BASE_URL``/``OPENROUTER_API_KEY`` env vars -- reused unchanged
from KAN-1287, not reinvented here.

What's new versus ``test_cli_llm_seat.py``: this ticket's e2e test plan asks
for two specific structural proofs, not just "the match completes":

1. **The autoplay seat's (``O``, ``AutoplayNarratorSeatController``) every
   move exactly matches its algorithm's ``best_action`` for that turn.**
   Proven by running with ``--json`` (one parseable JSON object per line,
   ``cli.py``'s ``run_match``), reconstructing the observation
   ``TicTacToeMinimaxAlgorithm`` would have seen before each of O's turns
   (the board from the immediately preceding turn's ``"state"`` -- X always
   moves first in this engine, so O's turn is never the first line and its
   predecessor is always X's just-played move), and independently
   recomputing a *fresh* ``TicTacToeMinimaxAlgorithm().recommend(...)`` call
   to compare against.
2. **The advised seat's (``X``, ``AdvisedLLMSeatController``) logged request
   payload contains the ``AlgorithmRecommendation`` each turn; a plain
   unadvised seat has none.** Proven using ``MockOpenRouterServer.
   received_requests`` (extended by this ticket to retain full decoded
   request bodies, not just a count) -- a positive check on the composite
   match below, and a negative/contrast check on a second, separate match
   using a plain ``--seat X=llm:openrouter/<model>`` (no modifier, the V3
   form) against a fresh server instance, proving *none* of its requests
   carry an ``"algorithm_recommendation"`` key.

**"A seat with no algorithm configured never has any ``GameAlgorithm``
called" (the test plan's third bullet)** is a structural fact, not something
this file adds elaborate runtime instrumentation to check: a plain
``llm:openrouter/<model>`` spec resolves, in ``cli.build_controller``, straight
to a bare ``OpenRouterBackend`` -- there is no code path from that spec to
``build_algorithm``/``ALGORITHM_REGISTRY``/any ``GameAlgorithm`` at all (see
``cli.py``'s modifier-detection branch, which only ever constructs an
algorithm when a ``:advised-by=``/``:narrated-by=`` modifier is present in
the spec string). The negative check in
``test_plain_unadvised_seat_has_no_algorithm_recommendation_payload`` below is
the same match a hidden per-call GameAlgorithm instrumentation test would
need anyway -- confirming empirically (via the request payloads actually
sent) what's already true by construction.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from examples.tictactoe.algorithm import TicTacToeMinimaxAlgorithm
from tests.e2e._mock_openrouter_server import MockOpenRouterServer

REPO_ROOT = Path(__file__).resolve().parents[2]

_MODEL = "openai/gpt-4o-mini"


def _subprocess_env(*, openrouter_base_url: str) -> dict[str, str]:
    """Mirrors ``test_cli_llm_seat.py``'s ``_subprocess_env`` exactly: repo
    root on ``PYTHONPATH``, plus a placeholder API key and the mock server's
    base URL, neither ever inherited as-is from the ambient environment."""
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = str(REPO_ROOT)
    env["OPENROUTER_API_KEY"] = "sk-test-placeholder-never-a-real-key"
    env["OPENROUTER_BASE_URL"] = openrouter_base_url
    return env


def _parse_json_lines(stdout: str) -> list[dict[str, Any]]:
    """Parse every ``--json`` line of ``stdout`` (skipping stray blank
    lines), in the order printed -- ``cli.py``'s ``run_match`` emits one
    ``{"type": "turn", ...}`` object per accepted move, then one final
    ``{"type": "result", ...}`` object."""
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def _parse_turn_lines(stdout: str) -> list[dict[str, Any]]:
    """The ``{"type": "turn", ...}`` subset of ``_parse_json_lines``, in
    order -- one entry per accepted move."""
    return [obj for obj in _parse_json_lines(stdout) if obj.get("type") == "turn"]


def test_advised_and_autoplay_seats_complete_a_match_with_exact_autoplay_moves() -> None:
    """The ticket's central e2e scenario: seat X is an
    ``AdvisedLLMSeatController`` (``llm:openrouter/<model>:advised-by=
    algo:tictactoe-minimax``), seat O is an ``AutoplayNarratorSeatController``
    (``algo:tictactoe-minimax:narrated-by=llm:openrouter/<model>``), both
    pointed at the same local mock OpenRouter server.

    Asserts, per the ticket's exact wording:

    - The match completes ("Game over." in stdout, exit code 0).
    - O's every move exactly matches a freshly, independently recomputed
      ``TicTacToeMinimaxAlgorithm().recommend(...)`` call on the observation
      it would have seen that turn.
    - X's logged request payload contains the ``AlgorithmRecommendation``
      (an ``"algorithm_recommendation"`` key with a ``best_action``) on at
      least one turn.
    """
    with MockOpenRouterServer() as server:
        result = subprocess.run(
            [
                "agf",
                "play",
                "tictactoe",
                "--seat",
                f"X=llm:openrouter/{_MODEL}:advised-by=algo:tictactoe-minimax",
                "--seat",
                f"O=algo:tictactoe-minimax:narrated-by=llm:openrouter/{_MODEL}",
                "--json",
            ],
            input="",  # zero human seats -- must complete fully unattended
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(openrouter_base_url=server.base_url),
        )

        assert result.returncode == 0, result.stderr
        # --json mode (needed below to reconstruct each turn's observation)
        # prints a final {"type": "result", ...} envelope instead of the
        # literal "Game over." text cli.py's plain-text mode prints --
        # see run_match's json_mode branch. The JSON result line is the
        # --json-mode equivalent proof the match reached a real conclusion.
        json_lines = _parse_json_lines(result.stdout)
        assert json_lines and json_lines[-1]["type"] == "result"
        assert server.request_count >= 1

        turns = _parse_turn_lines(result.stdout)
        assert turns, f"no 'turn' JSON lines found in stdout: {result.stdout!r}"
        assert any(t["seat"] == "X" for t in turns)
        o_turns = [t for t in turns if t["seat"] == "O"]
        assert o_turns, "the autoplay seat (O) never got a turn"

        # -- Guarantee 1: O's every move exactly matches its algorithm's
        # best_action, recomputed fresh and independently for that turn.
        fresh_algorithm = TicTacToeMinimaxAlgorithm()
        for turn_index, turn in enumerate(turns):
            if turn["seat"] != "O":
                continue
            # X always moves first in this engine (TicTacToeEngine.
            # initial_state's players[0]), so O's turn is never turns[0] --
            # the immediately preceding turn is always the board O actually
            # saw before deciding.
            assert turn_index >= 1
            prior_board = turns[turn_index - 1]["state"]["board"]
            observation = {"you": "O", "board": prior_board}
            legal_actions = [i for i, cell in enumerate(prior_board) if cell is None]
            expected = fresh_algorithm.recommend(observation, legal_actions)
            assert turn["action"] == expected.best_action, (
                f"O's move {turn['action']!r} on a board with legal_actions "
                f"{legal_actions!r} did not match the independently "
                f"recomputed best_action {expected.best_action!r}"
            )

        # -- Guarantee 2: X's (the advised seat's) logged request payload
        # contains the AlgorithmRecommendation each turn it was asked to
        # decide -- at least one captured request carries it.
        recommendation_payloads = []
        for request in server.received_requests:
            user_message = next(
                m["content"] for m in request["messages"] if m["role"] == "user"
            )
            sent_observation = json.loads(user_message)["observation"]
            if "algorithm_recommendation" in sent_observation:
                recommendation_payloads.append(sent_observation["algorithm_recommendation"])
        assert recommendation_payloads, (
            "no captured request carried an 'algorithm_recommendation' payload -- "
            "expected at least one from the advised seat (X)"
        )
        for payload in recommendation_payloads:
            assert "best_action" in payload


def test_plain_unadvised_seat_has_no_algorithm_recommendation_payload() -> None:
    """Contrast/negative check, run as a separate match against a fresh mock
    server: a plain, unadvised ``--seat X=llm:openrouter/<model>`` (the V3
    form, no ``:advised-by=`` modifier) never has any
    ``"algorithm_recommendation"`` key in any of its outgoing request
    payloads -- proving the plain form is completely unaffected by this
    ticket's new modifier machinery, and (per the test plan's third bullet)
    that no ``GameAlgorithm`` is ever involved for a seat that never
    configured one.
    """
    with MockOpenRouterServer() as server:
        result = subprocess.run(
            [
                "agf",
                "play",
                "tictactoe",
                "--seat",
                f"X=llm:openrouter/{_MODEL}",
                "--seat",
                "O=bot:random",
                "--json",
            ],
            input="",
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(openrouter_base_url=server.base_url),
        )

        assert result.returncode == 0, result.stderr
        json_lines = _parse_json_lines(result.stdout)
        assert json_lines and json_lines[-1]["type"] == "result"
        assert server.request_count >= 1
        assert server.received_requests

        for request in server.received_requests:
            user_message = next(
                m["content"] for m in request["messages"] if m["role"] == "user"
            )
            sent_observation = json.loads(user_message)["observation"]
            assert "algorithm_recommendation" not in sent_observation
