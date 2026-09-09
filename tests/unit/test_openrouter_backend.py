"""Unit tests for ``OpenRouterBackend`` (KAN-1284, ADR-0005, SLICES.md V3
step 1): no external calls, no subprocess -- per CLAUDE.md's rule that
"`OpenRouterBackend` (V3) and any live-API test must mock the HTTP call,"
every test here injects an ``httpx2.Client`` backed by ``httpx2.MockTransport``
so the real chat-completions endpoint is never touched.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

from agent_game_framework.agents import OpenRouterBackend, ResponseParseError
from agent_game_framework.core import SeatController, SeatDecision


def _client_returning(handler: Any) -> httpx2.Client:
    """Build a real ``httpx2.Client`` wired to a ``MockTransport`` so
    ``OpenRouterBackend`` exercises its actual HTTP-call code path
    (``client.post(...)`` / ``response.json()``) end to end, with the
    network swapped out for a scripted in-memory handler -- never a bare
    stand-in object standing in for ``httpx2.Client`` itself.
    """
    return httpx2.Client(
        base_url="https://openrouter.ai/api/v1", transport=httpx2.MockTransport(handler)
    )


def _chat_completion_response(status_code: int, arguments: Any, *, valid_json: bool = True) -> Any:
    """Build a ``MockTransport`` handler returning one well-formed-shaped
    chat-completions response whose sole tool-call's ``arguments`` is
    ``json.dumps(arguments)`` -- or, if ``valid_json`` is ``False``,
    ``arguments`` used verbatim as a raw (possibly non-JSON) string.
    """
    raw_arguments = arguments if not valid_json else json.dumps(arguments)

    def _handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status_code,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "submit_move",
                                        "arguments": raw_arguments,
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    return _handler


def test_decide_parses_a_well_formed_tool_call_response() -> None:
    """A well-formed mocked tool-call response is parsed into the correct
    ``(action, banter)`` pair, both landing correctly on the returned
    ``SeatDecision``."""
    client = _client_returning(
        _chat_completion_response(200, {"action": 4, "banter": "Taking the center!"})
    )
    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    decision = backend.decide({"board": [None] * 9}, legal_actions=[0, 1, 2, 3, 4, 5, 6, 7, 8])

    assert decision == SeatDecision(action=4, banter="Taking the center!")


def test_decide_parses_string_actions_too() -> None:
    client = _client_returning(
        _chat_completion_response(200, {"action": "paper", "banter": "Rock beats scissors, but..."})
    )
    backend = OpenRouterBackend[dict[str, Any], str](model="openai/gpt-4o-mini", client=client)

    decision = backend.decide({}, legal_actions=["rock", "paper", "scissors"])

    assert decision == SeatDecision(action="paper", banter="Rock beats scissors, but...")


def test_decide_defaults_banter_to_none_when_model_omits_it() -> None:
    """``banter`` is asked for but not strictly required to be present --
    a missing move is the real failure mode, not a missing banter line."""
    client = _client_returning(_chat_completion_response(200, {"action": 1}))
    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    decision = backend.decide({}, legal_actions=[0, 1, 2])

    assert decision.action == 1
    assert decision.banter is None


def test_decide_raises_response_parse_error_on_non_json_tool_arguments() -> None:
    """Malformed mocked response: the tool call's ``arguments`` string is not
    valid JSON at all (a model glitch/truncation) -- must raise
    ``ResponseParseError``, not crash with an uncaught ``json.JSONDecodeError``."""
    client = _client_returning(
        _chat_completion_response(200, "{not valid json at all", valid_json=False)
    )
    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    with pytest.raises(ResponseParseError):
        backend.decide({}, legal_actions=[0, 1, 2])


def test_decide_raises_response_parse_error_on_missing_action_field() -> None:
    """Malformed mocked response: valid JSON arguments, but missing the
    required ``action`` field entirely -- must raise ``ResponseParseError``,
    not crash with an uncaught ``KeyError``."""
    client = _client_returning(_chat_completion_response(200, {"banter": "no move given!"}))
    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    with pytest.raises(ResponseParseError):
        backend.decide({}, legal_actions=[0, 1, 2])


def test_decide_raises_response_parse_error_on_non_string_banter() -> None:
    """Malformed mocked response: ``banter`` present but the wrong type
    (a model returning a number instead of a string) -- must raise
    ``ResponseParseError``, not crash or silently coerce it."""
    client = _client_returning(_chat_completion_response(200, {"action": 1, "banter": 12345}))
    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    with pytest.raises(ResponseParseError):
        backend.decide({}, legal_actions=[0, 1, 2])


def test_decide_raises_response_parse_error_on_missing_tool_calls() -> None:
    """Malformed mocked response: the model replied with plain text instead
    of the forced tool call -- ``tool_calls`` is absent entirely. Must raise
    ``ResponseParseError``, not crash with an uncaught ``KeyError``."""

    def _handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"choices": [{"message": {"content": "I choose to pass, no tool needed."}}]},
        )

    client = _client_returning(_handler)
    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    with pytest.raises(ResponseParseError):
        backend.decide({}, legal_actions=[0, 1, 2])


def test_decide_raises_response_parse_error_on_non_json_body() -> None:
    """Malformed mocked response: the HTTP body isn't JSON at all. Must
    raise ``ResponseParseError``, not crash with an uncaught parse error
    from the underlying HTTP client."""

    def _handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"not json at all")

    client = _client_returning(_handler)
    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    with pytest.raises(ResponseParseError):
        backend.decide({}, legal_actions=[0, 1, 2])


def test_decide_does_not_validate_action_against_legal_actions() -> None:
    """``legal_actions`` is advisory context sent to the model, not something
    ``decide()`` re-validates its own return value against -- enforcement is
    ``Match.submit_action``'s job (ADR-0005), unchanged by this ticket. An
    out-of-list action from a well-formed response is returned as-is."""
    client = _client_returning(_chat_completion_response(200, {"action": 99, "banter": "oops"}))
    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    decision = backend.decide({}, legal_actions=[0, 1, 2])

    assert decision.action == 99


def test_request_payload_forces_the_submit_move_tool_and_sends_legal_actions() -> None:
    """The outgoing request is a constrained tool-call: exactly one tool
    (``submit_move``) is offered, ``tool_choice`` forces it, and its
    ``action`` schema is constrained to the given ``legal_actions`` via a
    JSON-schema ``enum`` -- proving this is a constrained tool-call request,
    not a free-text prompt the response happens to be scraped from."""
    captured: dict[str, Any] = {}

    def _handler(request: httpx2.Request) -> httpx2.Response:
        captured["payload"] = json.loads(request.content)
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
                                        "arguments": json.dumps({"action": 0, "banter": "go"}),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    client = _client_returning(_handler)
    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini", client=client)

    backend.decide({"board": [None] * 9}, legal_actions=[0, 3, 6])

    payload = captured["payload"]
    assert payload["model"] == "openai/gpt-4o-mini"
    assert len(payload["tools"]) == 1
    tool = payload["tools"][0]
    assert tool["function"]["name"] == "submit_move"
    assert tool["function"]["parameters"]["properties"]["action"]["enum"] == [0, 3, 6]
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "submit_move"}}


def test_constructor_raises_a_clear_error_when_no_api_key_or_client_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``client`` override, no explicit ``api_key``, and no
    ``OPENROUTER_API_KEY`` in the environment -- must raise a clear error at
    construction time rather than failing confusingly on the first
    ``decide()`` call."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini")


def test_constructor_reads_api_key_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no explicit ``client``/``api_key`` is given, the
    ``OPENROUTER_API_KEY`` environment variable is used to build a real
    client -- construction succeeds and no network call is made just to
    build the backend."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")

    backend = OpenRouterBackend[dict[str, Any], int](model="openai/gpt-4o-mini")

    assert backend is not None


def test_openrouter_backend_satisfies_seat_controller_protocol() -> None:
    client = _client_returning(
        _chat_completion_response(200, {"action": 1, "banter": "hi"})
    )
    controller: SeatController[dict[str, Any], int] = OpenRouterBackend(
        model="openai/gpt-4o-mini", client=client
    )
    decision = controller.decide({}, [0, 1, 2])
    assert isinstance(decision, SeatDecision)
