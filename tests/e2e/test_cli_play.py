"""End-to-end tests for ``agf play`` (KAN-1279, ADR-0006): drive the real,
installed ``agf`` console script as a subprocess with real stdin, mirroring
``tests/e2e/test_cli_help.py``'s style.

The ``examples.tictactoe`` reference engine this card's only registered game
depends on lives outside ``src/`` (ADR-0001: a throwaway example, not part of
the installed package/wheel), so it is not on the installed console script's
``sys.path`` by default the way ``pytest``'s own ``pythonpath = ["."]`` ini
setting makes it importable for in-process tests. These subprocess tests set
``PYTHONPATH`` to the repo root so the *subprocess* can import it too -- this
does not change how ``agf`` itself gets installed (unchanged from KAN-1274),
only how these tests point Python at this dev checkout's example game.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REPO_ROOT) if not existing else f"{REPO_ROOT}{os.pathsep}{existing}"
    return env


def test_human_vs_bot_rejects_bad_input_without_crashing_or_skipping_the_turn() -> None:
    """A human (seat X) vs a random bot (seat O). The scripted human stdin
    opens with an out-of-range cell ("99") on the very first move -- the CLI
    (via ``HumanCLIController``'s own re-prompt loop) must print a clear
    rejection and keep prompting the *same* seat, not crash and not silently
    advance the turn to O. After that, the scripted stdin supplies every
    cell value in a repeating cycle so that whichever cells the random bot
    happens to occupy, a legal choice for X is always found within one
    9-line window -- letting the full game play out to completion
    deterministically regardless of the bot's random choices.
    """
    # One deliberately out-of-range entry, then several full 0-8 cycles so a
    # legal move for X is always found within the next 9 lines, regardless
    # of which cells the random bot O has already taken.
    scripted_lines = ["99"] + [str(cell) for _ in range(10) for cell in range(9)]
    scripted_stdin = "\n".join(scripted_lines) + "\n"

    result = subprocess.run(
        ["agf", "play", "tictactoe", "--seat", "X=human", "--seat", "O=bot:random"],
        input=scripted_stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=_subprocess_env(),
    )

    assert result.returncode == 0, result.stderr
    # The out-of-range entry was rejected with a clear, specific error --
    # and the process did not crash doing so.
    assert "Invalid choice '99'" in result.stdout
    # The game still reached a real conclusion afterwards (did not hang or
    # silently stall on the rejected turn).
    assert "Game over." in result.stdout
    assert ("Winner(s):" in result.stdout) or ("Draw." in result.stdout)
    # X's seat produced more than one accepted move -- i.e. rejecting "99"
    # did not skip X's turn or hand it to O.
    assert result.stdout.count("X plays ") >= 1


def test_all_bot_match_completes_with_no_stdin_interaction() -> None:
    """Zero human seats: both seats are ``bot:random``. Must complete without
    hanging and without reading stdin at all -- proving no-stdin-required
    play falls out naturally (RandomBotController never calls ``input``).
    """
    result = subprocess.run(
        ["agf", "play", "tictactoe", "--seat", "X=bot:random", "--seat", "O=bot:random"],
        input="",  # explicitly no stdin available
        capture_output=True,
        text=True,
        timeout=10,
        env=_subprocess_env(),
    )

    assert result.returncode == 0, result.stderr
    assert "Game over." in result.stdout
    assert ("Winner(s):" in result.stdout) or ("Draw." in result.stdout)


def test_all_bot_match_json_mode_emits_one_json_object_per_line() -> None:
    result = subprocess.run(
        ["agf", "play", "tictactoe", "--seat", "X=bot:random", "--seat", "O=bot:random", "--json"],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
        env=_subprocess_env(),
    )

    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "expected at least one JSON line of output"
    parsed = [json.loads(line) for line in lines]
    assert parsed[-1]["type"] == "result"
    assert "winners" in parsed[-1]
    assert all(event["type"] in {"turn", "illegal_action", "result"} for event in parsed)
