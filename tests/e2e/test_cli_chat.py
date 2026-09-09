"""End-to-end tests for chat mode (ADR-0008, ADR-0009): a human seat vs. a
``Conversable`` seat, driven through the real, installed ``agf`` console
script.

Like ``tests/e2e/test_cli_llm_seat.py``, these spin up
``_mock_openrouter_server.MockOpenRouterServer`` and point the subprocess at
it via ``OPENROUTER_BASE_URL`` -- the mock now answers both request shapes
``OpenRouterBackend`` sends: a move-``decide()`` request (with the
``BANTER``-carrying tool-call response) and a chat-``respond()`` request
(with the ``CHAT_REPLY``-carrying plain response) -- see that module's
docstring for how it tells the two apart.

These are subprocess/fully-buffered-stdin tests, so they can't pin down the
exact real-time interleaving between "a chat line was typed" and "the
opponent's own decide() call happened to be in flight" the way
``tests/integration/test_live_match.py``'s ``threading.Event``-synchronized
tests do -- that concurrency guarantee is proven there. What these tests
prove instead is that the CLI's own chat wiring (``cmd_play`` detecting a
chattable opponent, swapping in a ``ChattableHumanController``, and driving
``run_live_match_with_chat``) works correctly end to end through the real
console script: a chat line gets a reply printed, an ordinary move still
gets submitted, and the match still completes normally.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.e2e._mock_openrouter_server import BANTER, CHAT_REPLY, MockOpenRouterServer

REPO_ROOT = Path(__file__).resolve().parents[2]


def _subprocess_env(*, openrouter_base_url: str) -> dict[str, str]:
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = str(REPO_ROOT)
    env["OPENROUTER_API_KEY"] = "sk-test-placeholder-never-a-real-key"
    env["OPENROUTER_BASE_URL"] = openrouter_base_url
    return env


def test_chat_reply_is_printed_and_the_game_still_completes() -> None:
    """A ``"chat: ..."``-prefixed line on X's own first turn is sent as chat
    (never mistaken for a move); a plain unprefixed line sent right
    afterward -- once it's O's turn -- is also chat, no prefix needed. The
    game still reaches a normal conclusion via ordinary scripted moves
    (mirroring ``test_cli_llm_seat.py``'s repeating-0-8-cycle pattern, so a
    legal move for X is always found regardless of which cells the mocked
    ``O`` -- always playing ``enum[0]`` -- has already taken).
    """
    scripted_lines = [
        "chat: hi there, good luck!",
        "how are you feeling about this game?",
    ] + [str(cell) for _ in range(10) for cell in range(9)]
    scripted_stdin = "\n".join(scripted_lines) + "\n"

    with MockOpenRouterServer() as server:
        result = subprocess.run(
            [
                "agf",
                "play",
                "tictactoe",
                "--seat",
                "X=human",
                "--seat",
                "O=llm:openrouter/openai/gpt-4o-mini",
            ],
            input=scripted_stdin,
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(openrouter_base_url=server.base_url),
        )

        assert result.returncode == 0, result.stderr
        assert "Game over." in result.stdout
        assert ("Winner(s):" in result.stdout) or ("Draw." in result.stdout)
        # A move-decision banter line was printed, exactly as in the
        # non-chat LLM-seat e2e tests.
        assert BANTER in result.stdout
        # And at least one chat reply was printed too, distinct from banter.
        assert f"O (chat): {CHAT_REPLY}" in result.stdout
        # The subprocess talked to the local mock for both request shapes.
        assert server.request_count >= 2


def test_non_chattable_opponent_is_unaffected_by_chat_mode() -> None:
    """A human vs. ``bot:random`` (no ``Conversable`` seat at all) must not
    engage chat mode -- an out-of-range/occupied-cell entry is still
    rejected with the plain ``HumanCLIController`` "Invalid choice" message,
    never routed to a nonexistent chat channel."""
    scripted_stdin = "\n".join(["99"] + [str(cell) for _ in range(10) for cell in range(9)]) + "\n"

    result = subprocess.run(
        ["agf", "play", "tictactoe", "--seat", "X=human", "--seat", "O=bot:random"],
        input=scripted_stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )

    assert result.returncode == 0, result.stderr
    assert "Invalid choice '99'" in result.stdout
    assert "Game over." in result.stdout
    assert "(chat)" not in result.stdout
