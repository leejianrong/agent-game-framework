"""Unit tests for ``HumanCLIController`` (KAN-1278, ADR-0005): no external
calls, no subprocess, no real interactive stdin -- ``input_fn``/``print_fn``
are scripted fakes injected via the constructor.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from agent_game_framework.agents import HumanCLIController
from agent_game_framework.core import SeatController, SeatDecision


def _silent_print(*args: Any, **kwargs: Any) -> None:
    """A ``print_fn`` that discards output -- tests here only assert on
    ``decide()``'s return value and the injected ``input_fn``'s call count."""


def _scripted_input(responses: list[str]) -> tuple[list[str], object]:
    """Return an ``input_fn`` that yields ``responses`` in order and a call
    log (a plain list, appended to on every call) for assertions."""
    calls: list[str] = []
    iterator: Iterator[str] = iter(responses)

    def _input_fn() -> str:
        value = next(iterator)
        calls.append(value)
        return value

    return calls, _input_fn


def test_decide_returns_the_legal_action_on_a_correct_first_attempt() -> None:
    calls, input_fn = _scripted_input(["4"])
    controller = HumanCLIController[dict[str, Any], int](input_fn=input_fn, print_fn=_silent_print)

    decision = controller.decide({"board": [None] * 9}, [0, 1, 2, 3, 4, 5, 6, 7, 8])

    assert decision == SeatDecision(action=4, banter=None)
    assert len(calls) == 1


def test_decide_reprompts_on_unparseable_input_then_succeeds() -> None:
    calls, input_fn = _scripted_input(["banana", "2"])
    controller = HumanCLIController[dict[str, Any], int](input_fn=input_fn, print_fn=_silent_print)

    decision = controller.decide({"board": [None] * 9}, [0, 1, 2])

    assert decision.action == 2
    assert len(calls) > 1


def test_decide_reprompts_on_illegal_but_parseable_input_then_succeeds() -> None:
    """``"9"`` parses as an int but is out of the given ``legal_actions`` --
    must re-prompt rather than returning it."""
    calls, input_fn = _scripted_input(["9", "0"])
    controller = HumanCLIController[dict[str, Any], int](input_fn=input_fn, print_fn=_silent_print)

    decision = controller.decide({"board": [None] * 9}, [0, 1, 2])

    assert decision.action == 0
    assert len(calls) > 1


def test_decide_banter_is_always_none() -> None:
    for responses in (["1"], ["oops", "1"], ["99", "-1", "1"]):
        _, input_fn = _scripted_input(responses)
        controller = HumanCLIController[dict[str, Any], int](
            input_fn=input_fn, print_fn=_silent_print
        )
        decision = controller.decide({}, [1, 2, 3])
        assert decision.banter is None


def test_decide_matches_string_legal_actions_too() -> None:
    calls, input_fn = _scripted_input(["paper"])
    controller = HumanCLIController[dict[str, Any], str](input_fn=input_fn, print_fn=_silent_print)

    decision = controller.decide({}, ["rock", "paper", "scissors"])

    assert decision == SeatDecision(action="paper", banter=None)
    assert len(calls) == 1


def test_decide_prints_the_observation_and_legal_actions() -> None:
    printed: list[tuple[Any, ...]] = []

    def _print_fn(*args: Any, **kwargs: Any) -> None:
        printed.append(args)

    _, input_fn = _scripted_input(["1"])
    controller = HumanCLIController[dict[str, Any], int](input_fn=input_fn, print_fn=_print_fn)

    controller.decide({"you": "X"}, [1, 2])

    assert any({"you": "X"} in call for call in printed)
    assert any([1, 2] in call for call in printed)


def test_human_cli_controller_satisfies_seat_controller_protocol() -> None:
    _, input_fn = _scripted_input(["1"])
    controller: SeatController[dict[str, Any], int] = HumanCLIController(
        input_fn=input_fn, print_fn=_silent_print
    )
    decision = controller.decide({}, [1, 2])
    assert isinstance(decision, SeatDecision)


def test_decide_raises_if_scripted_input_is_exhausted_without_a_legal_choice() -> None:
    """Sanity check on the test helper itself: an unlimited illegal-input
    stream would loop forever, so the helper should surface exhaustion as a
    clear error rather than hanging the test suite."""
    _, input_fn = _scripted_input(["nope"])
    controller = HumanCLIController[dict[str, Any], int](input_fn=input_fn, print_fn=_silent_print)

    with pytest.raises(StopIteration):
        controller.decide({}, [1, 2, 3])
