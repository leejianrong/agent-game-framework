"""End-to-end: ``agf play secretnumber`` drives a free-text move and a
``--config`` value through the real console script (ADR-0010, ADR-0011)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REPO_ROOT) if not existing else f"{REPO_ROOT}{os.pathsep}{existing}"
    return env


def _events(stdout: str) -> list[dict[str, Any]]:
    """JSON envelopes in ``stdout``. The human prompt ends without a newline,
    so an envelope may follow ``"Your move: "`` on the same line."""
    found = []
    for line in stdout.splitlines():
        start = line.find('{"type"')
        if start != -1:
            found.append(json.loads(line[start:]))
    return found


def _play(stdin: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["agf", "play", "secretnumber", "--seat", "A=human", "--seat", "B=bot:random", *extra],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=_env(),
    )


def test_human_holder_types_a_free_text_hint_and_the_bot_guesses() -> None:
    result = _play("\nwarm and smoky\n", "--config", "secret=7", "--json")

    assert result.returncode == 0, result.stderr
    events = _events(result.stdout)
    assert events[0]["type"] == "turn"
    assert events[0]["seat"] == "A"
    assert events[0]["action"] == "warm and smoky"
    # the holder is the human viewer, so seeing their own secret is correct
    assert events[0]["state"]["secret"] == 7
    assert events[-1]["type"] == "result"


def test_a_bad_hint_is_rejected_by_the_engine_and_asked_again() -> None:
    # "the number 7" names the secret; the engine rejects it via Match, the
    # human is asked again and the second hint is accepted.
    result = _play("the number 7\nsmoky\n", "--config", "secret=7", "--json")

    assert result.returncode == 0, result.stderr
    kinds = [event["type"] for event in _events(result.stdout)]
    assert kinds[0] == "illegal_action"
    assert "turn" in kinds


def test_malformed_config_is_a_usage_error() -> None:
    result = _play("", "--config", "nonsense")

    assert result.returncode == 2
    assert "KEY=VALUE" in result.stdout
