"""Integration tests: a hidden-information, free-text game (Secret Number)
through ``Match``, the CLI's ``--json`` viewer scoping, and the MCP server's
viewer-scoped dumps and seat binding (ADR-0010, ADR-0011)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

from mcp import Client

from agent_game_framework.agents import HumanCLIController
from agent_game_framework.cli import run_match
from agent_game_framework.connectors.mcp import build_server
from agent_game_framework.core import FreeText, Match, SeatDecision
from examples.secretnumber import SecretNumberEngine

SECRET = 7


class _HintBot:
    """A scripted holder: writes a fixed hint, never anything else."""

    def decide(self, observation: Any, legal_actions: list[Any]) -> SeatDecision[Any]:
        assert legal_actions == [FreeText(max_words=5)]
        return SeatDecision(action="warm and smoky", banter=None)


def _match(**seats: Any) -> Match[Any, Any, Any]:
    return Match(
        SecretNumberEngine(),
        players=["A", "B"],
        config={"secret": SECRET},
        seats=seats or None,
    )


def test_cli_json_for_a_human_guesser_never_contains_the_secret() -> None:
    lines: Iterator[str] = iter(["3"])
    match = _match(
        A=_HintBot(),
        B=HumanCLIController(input_fn=lambda: next(lines), print_fn=lambda *a, **k: None),
    )
    out: list[str] = []

    run_match(
        match, json_mode=True, print_fn=lambda *a: out.append(" ".join(map(str, a))), viewer="B"
    )

    turns = [json.loads(line) for line in out]
    # the hint turn (A) is shown from B's viewpoint, so no secret before the end;
    assert "secret" not in turns[0]["state"]
    # the guess ended the game, which reveals it by the game's own rules
    assert turns[-1]["type"] == "result"


def test_cli_json_without_a_viewer_is_the_full_dump() -> None:
    lines: Iterator[str] = iter(["3"])
    match = _match(
        A=_HintBot(),
        B=HumanCLIController(input_fn=lambda: next(lines), print_fn=lambda *a, **k: None),
    )
    out: list[str] = []

    run_match(match, json_mode=True, print_fn=lambda *a: out.append(" ".join(map(str, a))))

    assert json.loads(out[0])["state"]["secret"] == SECRET


def _call(server: Any, tool: str, args: dict[str, Any]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(go())


def test_mcp_dump_and_submit_return_only_the_callers_observation() -> None:
    match = _match()
    server = build_server(match)

    submitted = _call(server, "submit_action", {"player": "A", "action": "warm and smoky"})
    guesser_dump = _call(server, "get_state_dump", {"player": "B"})

    assert not submitted.is_error
    assert submitted.structured_content["secret"] == SECRET  # the holder's own view
    assert not guesser_dump.is_error
    assert "secret" not in guesser_dump.structured_content
    assert guesser_dump.structured_content["hint"] == "warm and smoky"


def test_mcp_bound_seat_refuses_to_read_another_seat() -> None:
    match = _match()
    server = build_server(match, bound_seat="B")

    refused = _call(server, "get_observation", {"player": "A"})
    own = _call(server, "get_observation", {})

    assert refused.is_error
    assert "secret" not in json.dumps(refused.structured_content or refused.content, default=str)
    assert not own.is_error
    assert own.structured_content["role"] == "guesser"


def test_mcp_free_text_legal_action_and_rejection() -> None:
    match = _match()
    server = build_server(match)

    listed = _call(server, "list_legal_actions", {"player": "A"})
    bad = _call(server, "submit_action", {"player": "A", "action": "the number 7"})

    assert "free_text" in json.dumps(listed.structured_content or listed.content, default=str)
    assert bad.is_error
    assert match.observation_for("A")["hint"] is None  # state unchanged


def test_mcp_omniscient_restores_the_full_dump() -> None:
    match = _match()
    server = build_server(match, omniscient=True)

    dump = _call(server, "get_state_dump", {})

    assert dump.structured_content["secret"] == SECRET
