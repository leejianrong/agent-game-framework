"""End-to-end tests for an ``llm:openrouter/<model>`` seat driven through the
real, installed ``agf`` console script (KAN-1287, ADR-0005, ADR-0006,
SLICES.md V3 "End-to-end" test plan). This is the last card in epic V3 --
merging it closes the epic.

Like ``tests/e2e/test_cli_play.py``, these drive ``agf`` as a real
subprocess with real stdin, and (per that file's docstring) set
``PYTHONPATH`` to the repo root so the subprocess can import
``examples.tictactoe`` (ADR-0001: it lives outside ``src/``).

What's new here versus ``test_cli_play.py``: an ``llm:openrouter/<model>``
seat's ``OpenRouterBackend``, built inside the subprocess, makes a real HTTP
call over a real OS socket -- there is no in-process seam
(``httpx2.MockTransport``) that can intercept a separate process's sockets.
So every test below spins up ``_mock_openrouter_server.MockOpenRouterServer``
(a local, ``127.0.0.1``-only, stdlib-only HTTP server -- see that module's
docstring for the full reasoning) and points the subprocess at it via the
``OPENROUTER_BASE_URL`` environment variable, which ``OpenRouterBackend.
__init__`` now falls back to when no explicit ``base_url``/``client`` is
given (KAN-1287). ``OPENROUTER_API_KEY`` is set to an explicit placeholder
string in the subprocess env (never inherited from the ambient environment,
even if the machine running these tests happens to have a real key set) --
the mock server never validates it, so any non-empty string works, and no
real key is ever at risk of being sent anywhere.

Safety, structurally guaranteed rather than merely asserted: the mock server
binds only to ``127.0.0.1`` (never ``0.0.0.0``), and the subprocess env built
here never contains a real ``OPENROUTER_API_KEY``/points ``OPENROUTER_BASE_URL``
anywhere but the local mock -- so no real network call to ``openrouter.ai``
is reachable from these tests at all. As an extra guardrail, each test also
asserts ``server.request_count >= 1``, proving the subprocess actually did
talk to the local mock rather than silently falling through to some other
path.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.e2e._mock_openrouter_server import BANTER, MockOpenRouterServer

REPO_ROOT = Path(__file__).resolve().parents[2]


def _subprocess_env(*, openrouter_base_url: str) -> dict[str, str]:
    """Build the subprocess environment: repo root on ``PYTHONPATH`` (mirrors
    ``test_cli_play.py``'s ``_subprocess_env()``), plus an explicit
    placeholder ``OPENROUTER_API_KEY`` and ``OPENROUTER_BASE_URL`` pointed at
    the local mock server -- both added fresh, never inherited from
    ``os.environ`` as-is, so a real key/endpoint on the host running these
    tests can never leak into the subprocess.
    """
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = str(REPO_ROOT)
    env["OPENROUTER_API_KEY"] = "sk-test-placeholder-never-a-real-key"
    env["OPENROUTER_BASE_URL"] = openrouter_base_url
    return env


def test_human_vs_openrouter_backend_completes_with_banter() -> None:
    """Human (seat X) vs ``llm:openrouter/<model>`` (seat O). X's stdin is
    scripted as a repeating 0-8 cycle (mirroring
    ``test_cli_play.py``'s bad-input test) so a legal move for X is always
    found regardless of which cells O -- the mocked LLM, always picking the
    first legal action -- has already taken; this test does not need to pin
    down one exact winning line to prove the ticket's actual requirement:
    the game completes, and a banter line is printed for at least one of O's
    turns.
    """
    scripted_stdin = "\n".join(str(cell) for _ in range(10) for cell in range(9)) + "\n"

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
        # O's mocked responses all carry the same fixed banter string --
        # printed by cli.py's run_match alongside O's move.
        assert BANTER in result.stdout
        # O actually played at least once (the match reached O's turn).
        assert result.stdout.count("O plays ") >= 1
        # The subprocess really talked to the local mock, not something else.
        assert server.request_count >= 1


def test_all_ai_match_with_one_openrouter_seat_completes_unattended() -> None:
    """All-AI, zero human seats, one of which is ``llm:openrouter/<model>``:
    seat X is the mocked ``OpenRouterBackend``, seat O is ``bot:random``. No
    stdin at all (mirroring ``test_cli_play.py``'s
    ``test_all_bot_match_completes_with_no_stdin_interaction``) -- the match
    must complete fully unattended, and X's mocked responses must still
    produce a banter line in the output.
    """
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
            input="",  # explicitly no stdin available
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(openrouter_base_url=server.base_url),
        )

        assert result.returncode == 0, result.stderr
        assert "Game over." in result.stdout
        assert ("Winner(s):" in result.stdout) or ("Draw." in result.stdout)
        assert BANTER in result.stdout
        assert result.stdout.count("X plays ") >= 1
        assert server.request_count >= 1
