"""Integration tests for ``Match``'s handling of a real ``OpenRouterBackend``
seat (ADR-0005, SLICES.md V3 step 2, KAN-1285): a real ``OpenRouterBackend``
instance, wired to a mocked ``httpx2`` transport (per CLAUDE.md's rule that
any live-API test must mock the HTTP call), driven through the real
``Match``/``TicTacToeEngine`` -- in-process, no subprocess, no real network.

This module deliberately does **not** re-test ``OpenRouterBackend``'s own
response-parsing logic (that's ``tests/unit/test_openrouter_backend.py``'s
job); it tests only ``Match``'s reaction to the two ways an
``OpenRouterBackend.decide()`` call can go wrong end to end:

- a well-formed-but-illegal action (an occupied Tic-Tac-Toe cell) -- must
  raise ``IllegalActionError``, exactly as any other controller kind's
  illegal action would (SLICES.md V3 test plan, first bullet). This is a
  regression/confirmation test: per this ticket's design (see the PR
  description), the pre-existing ``submit_action``/``IllegalActionError``
  path already treats every ``SeatController`` uniformly, so no production
  code changed to make this pass.
- a ``decide()`` call that raises twice in a row (an HTTP timeout, or a
  response that fails to parse into a ``SeatDecision`` at all) -- must
  surface as ``AgentTimeoutError`` after ``Match``'s internal
  reject-and-reprompt-once retry, not hang the turn loop or crash with a
  raw ``httpx2``/``ResponseParseError`` exception type (SLICES.md V3 test
  plan, second bullet). This *is* new behavior, added to ``Match.play_turn``
  by this ticket.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import httpx2
import pytest

from agent_game_framework.agents import OpenRouterBackend
from agent_game_framework.core import AgentTimeoutError, IllegalActionError, Match
from examples.tictactoe import TicTacToeEngine

TicTacToeMatch = Match[Any, int, Any]


def _client_returning(handler: Any) -> httpx2.Client:
    """Build a real ``httpx2.Client`` wired to a ``MockTransport``, the same
    seam ``tests/unit/test_openrouter_backend.py`` uses -- so
    ``OpenRouterBackend`` exercises its actual HTTP-call code path with the
    network swapped out for a scripted in-memory handler.
    """
    return httpx2.Client(
        base_url="https://openrouter.ai/api/v1", transport=httpx2.MockTransport(handler)
    )


def _tool_call_response(action: Any, banter: str = "here goes") -> Any:
    """A ``MockTransport`` handler returning one well-formed chat-completions
    response whose forced ``submit_move`` tool call carries ``action``."""

    def _handler(request: httpx2.Request) -> httpx2.Response:
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
                                            {"action": action, "banter": banter}
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    return _handler


def _always_times_out(request: httpx2.Request) -> httpx2.Response:
    """A ``MockTransport`` handler simulating a network timeout on every
    call -- ``OpenRouterBackend.decide()`` lets this ``httpx2`` exception
    propagate raw (it never catches network-level exceptions, only response-
    parsing failures), which is exactly the "malformed/unavailable response"
    shape ``Match.play_turn`` must catch generically."""
    raise httpx2.ReadTimeout("simulated OpenRouter API timeout", request=request)


def test_openrouter_backend_illegal_action_raises_illegal_action_error_state_unchanged() -> None:
    """A mocked API response containing a well-formed-but-illegal action (an
    already-occupied cell) drives ``Match.submit_action``/``play_turn()`` to
    raise ``IllegalActionError`` -- the same exception type, and the same
    state-unchanged guarantee, as any other controller kind's illegal move
    (ADR-0005's "never handled differently because the seat happens to be
    human" -- proven here for the AI-backed case too).
    """
    client = _client_returning(_tool_call_response(action=0))
    x_backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    engine = TicTacToeEngine()
    # X's mocked response always proposes cell 0 -- legal on X's first turn,
    # illegal (already occupied) on X's second. Drive the match so X gets a
    # second turn with cell 0 already taken: X plays 0, O plays elsewhere
    # (via submit_action, bypassing X's controller entirely), then X is
    # asked to decide again and its mocked response repeats the now-illegal
    # cell 0.
    match: TicTacToeMatch = Match(engine, players=["X", "O"], seats={"X": x_backend})
    match.play_turn()  # X's mocked response plays cell 0 -- legal, board's first move.
    assert match.current_players() == ["O"]
    match.submit_action("O", 1)  # O plays elsewhere; back to X.
    before = match.serialize()

    with pytest.raises(IllegalActionError):
        match.play_turn()  # X's mocked response proposes cell 0 again -- now occupied.

    assert match.serialize() == before
    assert match.current_players() == ["X"]


def test_openrouter_backend_repeated_failure_surfaces_as_agent_timeout_error() -> None:
    """A mocked API timeout on every call drives ``OpenRouterBackend.decide()``
    to raise (an ``httpx2`` network exception, uncaught by
    ``OpenRouterBackend`` itself -- see its module docstring) on both of
    ``Match``'s attempts. ``Match.play_turn()`` must surface this as
    ``AgentTimeoutError`` after exactly one internal retry, not hang the
    turn loop and not let the raw ``httpx2`` exception type escape.
    """
    client = _client_returning(_always_times_out)
    x_backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    engine = TicTacToeEngine()
    match: TicTacToeMatch = Match(engine, players=["X", "O"], seats={"X": x_backend})
    before = match.serialize()

    with pytest.raises(AgentTimeoutError) as exc_info:
        match.play_turn()

    assert isinstance(exc_info.value.__cause__, httpx2.ReadTimeout)
    # Nothing was ever submitted -- X is still up, state is untouched.
    assert match.serialize() == before
    assert match.current_players() == ["X"]


def test_openrouter_backend_recovers_if_only_the_first_attempt_times_out() -> None:
    """The reject-and-reprompt-once policy actually helps: if only the
    *first* ``decide()`` call fails (a transient timeout) and the second
    succeeds, ``Match.play_turn()`` completes normally -- no
    ``AgentTimeoutError``, no special-casing versus any other controller.
    """
    call_count = itertools.count()

    def _fails_once_then_succeeds(request: httpx2.Request) -> httpx2.Response:
        if next(call_count) == 0:
            raise httpx2.ReadTimeout("simulated transient timeout", request=request)
        return _tool_call_response(action=4)(request)

    client = _client_returning(_fails_once_then_succeeds)
    x_backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    engine = TicTacToeEngine()
    match: TicTacToeMatch = Match(engine, players=["X", "O"], seats={"X": x_backend})

    match.play_turn()  # must not raise -- the retry recovers.

    assert match.current_players() == ["O"]
    assert match.serialize()["board"][4] == "X"
