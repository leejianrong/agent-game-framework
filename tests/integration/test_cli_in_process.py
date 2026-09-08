"""Integration test for the CLI skeleton, driven in-process (no subprocess)."""

import pytest

from agent_game_framework.cli import main


def test_help_exits_zero_in_process() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


def test_no_args_exits_zero_in_process() -> None:
    assert main([]) == 0
