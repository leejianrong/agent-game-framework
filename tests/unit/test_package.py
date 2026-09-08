"""Unit tests for the package skeleton (KAN-1274): no external calls, no subprocess."""

from agent_game_framework import __version__


def test_version_is_a_nonempty_string() -> None:
    assert isinstance(__version__, str)
    assert __version__
