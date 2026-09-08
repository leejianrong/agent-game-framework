"""End-to-end test: this card's own acceptance criterion (docs/SLICES.md, V1 e2e)
is that ``agf --help`` runs after a pip/uv install -- so exercise the installed
console script as a real subprocess, not the Python function directly.
"""

import subprocess
import sys


def test_agf_help_runs_and_exits_zero() -> None:
    result = subprocess.run(
        ["agf", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "agf" in result.stdout.lower()


def test_agf_help_via_python_module_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "agent_game_framework.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
