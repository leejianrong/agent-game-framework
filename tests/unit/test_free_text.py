"""Unit tests for the free-text action marker (ADR-0010) and the adapters that
understand it: ``HumanCLIController``, ``OpenRouterBackend``, the CLI's chat
move matcher, ``--config`` parsing and ``BOT_REGISTRY``. No external calls."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

from agent_game_framework import cli
from agent_game_framework.agents import HumanCLIController, OpenRouterBackend, RandomBotController
from agent_game_framework.core import FreeText, SeatDecision, is_free_text


def _silent(*args: Any, **kwargs: Any) -> None:
    pass


def test_describe_lists_only_the_stated_constraints() -> None:
    assert FreeText().describe() == "a single line of free text"
    assert "at most 6 words" in FreeText(max_words=6).describe()
    assert "at most 80 characters" in FreeText(max_chars=80).describe()


def test_is_free_text_only_matches_a_lone_marker() -> None:
    marker = FreeText(max_words=3)
    assert is_free_text([marker]) is marker
    assert is_free_text([1, 2, 3]) is None
    assert is_free_text([]) is None
    assert is_free_text([marker, marker]) is None


def test_human_returns_a_typed_line_stripped_and_reprompts_on_empty() -> None:
    lines: Iterator[str] = iter(["", "   ", "  smoky and warm  "])
    controller = HumanCLIController[dict[str, Any], Any](
        input_fn=lambda: next(lines), print_fn=_silent
    )

    decision = controller.decide({}, [FreeText(max_words=5)])

    assert decision == SeatDecision(action="smoky and warm", banter=None)


def _capture(sink: list[dict[str, Any]], action: Any) -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        sink.append(json.loads(request.content))
        args = json.dumps({"action": action, "banter": "ok"})
        return httpx2.Response(
            200,
            json={"choices": [{"message": {"tool_calls": [{"function": {"arguments": args}}]}}]},
        )

    return handler


def _backend(handler: Any) -> OpenRouterBackend[Any, Any]:
    client = httpx2.Client(
        base_url="https://openrouter.ai/api/v1", transport=httpx2.MockTransport(handler)
    )
    return OpenRouterBackend(model="m", client=client)


def test_openrouter_free_text_sends_a_string_schema_not_an_enum() -> None:
    seen: list[dict[str, Any]] = []
    backend = _backend(_capture(seen, "smoky and warm"))

    decision = backend.decide({"secret": 3}, [FreeText(max_words=5, max_chars=40)])

    assert decision.action == "smoky and warm"
    schema = seen[0]["tools"][0]["function"]["parameters"]["properties"]["action"]
    assert schema["type"] == "string"
    assert schema["maxLength"] == 40
    assert "enum" not in schema
    user = json.loads(seen[0]["messages"][1]["content"])
    assert "at most 5 words" in user["legal_actions"]["free_text"]
    assert "free-text" in seen[0]["messages"][0]["content"]


def test_openrouter_enumerated_actions_still_send_an_enum() -> None:
    seen: list[dict[str, Any]] = []
    backend = _backend(_capture(seen, 2))

    backend.decide({}, [0, 1, 2])

    schema = seen[0]["tools"][0]["function"]["parameters"]["properties"]["action"]
    assert schema["enum"] == [0, 1, 2]
    assert "free-text" not in seen[0]["messages"][0]["content"]


def test_chat_matcher_takes_any_line_as_free_text_but_keeps_the_chat_prefix() -> None:
    pending = [FreeText()]
    assert cli._match_legal_action("smoky and warm", pending) == "smoky and warm"
    assert cli._match_legal_action("chat: why that spectrum?", pending) is None


def test_chat_matcher_unchanged_for_enumerated_actions() -> None:
    assert cli._match_legal_action("4", [3, 4]) == 4
    assert cli._match_legal_action("9", [3, 4]) is None


def test_parse_config_args_parses_json_values_else_strings() -> None:
    config = cli.parse_config_args(["rounds=6", "fast=true", "deck=my deck.json", "seed=null"])
    assert config == {"rounds": 6, "fast": True, "deck": "my deck.json", "seed": None}


@pytest.mark.parametrize("bad", ["rounds", "=3"])
def test_parse_config_args_rejects_malformed_items(bad: str) -> None:
    with pytest.raises(ValueError):
        cli.parse_config_args([bad])


def test_bot_registry_resolves_bot_specs_and_keeps_bot_random(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = RandomBotController()
    monkeypatch.setitem(cli.BOT_REGISTRY, "mine", lambda: sentinel)

    assert cli.build_controller("bot:mine") is sentinel
    assert isinstance(cli.build_controller("bot:random"), RandomBotController)
    with pytest.raises(cli.SeatSpecError):
        cli.build_controller("bot:nope")
