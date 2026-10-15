"""End-to-end test for the all-AI "banter exchange" mode (no human seat):
two ``llm:openrouter/<model>`` seats trash-talk each other spontaneously,
one reply per banter-carrying move, driven through the real, installed
``agf`` console script (mirrors ``tests/e2e/test_cli_chat.py``'s structure,
but for zero human seats instead of one human + one AI).

Like ``test_cli_chat.py``, this points the subprocess at
``_mock_openrouter_server.MockOpenRouterServer``, which already answers both
request shapes ``OpenRouterBackend`` sends: a move-``decide()`` call (with
the ``BANTER``-carrying tool-call response) and a chat/``respond()`` call
(with the ``CHAT_REPLY``-carrying plain response) -- exactly what
``_make_banter_exchange_hook``'s reply calls trigger, no new mock needed.

No stdin scripting at all here (unlike the chat-mode tests): with zero human
seats, ``cmd_play`` never reads stdin, so ``subprocess.run`` is given empty
input.
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


def test_two_ai_seats_trash_talk_each_other_with_no_human_and_the_game_still_completes() -> None:
    with MockOpenRouterServer() as server:
        result = subprocess.run(
            [
                "agf",
                "play",
                "tictactoe",
                "--seat",
                "X=llm:openrouter/openai/gpt-4o-mini",
                "--seat",
                "O=llm:openrouter/anthropic/claude-3.5-sonnet",
            ],
            input="",
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(openrouter_base_url=server.base_url),
        )

        assert result.returncode == 0, result.stderr
        assert "Game over." in result.stdout
        assert ("Winner(s):" in result.stdout) or ("Draw." in result.stdout)
        # Every move carries the mocked banter line...
        assert BANTER in result.stdout
        # ...and the *other* seat spontaneously replies to it, addressed by
        # name -- both directions, since both X and O move at least once.
        assert f'O (reply to X): "{CHAT_REPLY}' in result.stdout
        assert f'X (reply to O): "{CHAT_REPLY}' in result.stdout
        # No human seat exists, so this must never be chat mode's own
        # "human (chat): ..." rendering -- a different code path entirely.
        assert "(chat):" not in result.stdout
        assert server.request_count >= 2


def test_single_ai_seat_vs_a_bot_gets_no_banter_exchange() -> None:
    """Only one seat is ``Conversable`` here (``bot:random`` isn't) -- the
    ``len(conversable_seats) >= 2`` guard must keep this on the plain
    ``run_match`` path with ordinary per-move banter only, no reply lines."""
    with MockOpenRouterServer() as server:
        result = subprocess.run(
            [
                "agf",
                "play",
                "tictactoe",
                "--seat",
                "X=llm:openrouter/openai/gpt-4o-mini",
                "--seat",
                "O=bot:random",
            ],
            input="",
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(openrouter_base_url=server.base_url),
        )

        assert result.returncode == 0, result.stderr
        assert "Game over." in result.stdout
        assert BANTER in result.stdout
        assert "(reply to" not in result.stdout
