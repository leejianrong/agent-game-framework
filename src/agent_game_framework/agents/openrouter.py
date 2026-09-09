"""``OpenRouterBackend``: an LLM-backed ``SeatController`` (ADR-0005, KAN-1284,
SLICES.md V3 step 1).

Per ADR-0005, ``OpenRouterBackend`` is "the only concrete `AgentBackend`
built this milestone (stateless, works headless in CI/integration tests,
needs only an API key, no local GPU)." It sends the observation and
``legal_actions`` to an OpenRouter chat-completions endpoint as a
*constrained* tool/function-call request -- one tool, ``submit_move``, whose
JSON-schema parameters require an ``action`` field (constrained to
``legal_actions`` via a schema ``enum``, so a well-behaved model literally
cannot emit a value outside the list) plus a free-text ``banter`` field --
and parses the model's forced tool call back into a ``SeatDecision``.

Scope note (read this before changing the error-handling here): this module
raises ``ResponseParseError``, never ``IllegalActionError``/
``AgentTimeoutError``. Per ADR-0005, "illegal or malformed decisions from
any controller ... are rejected by the `Match` orchestrator ... via
`IllegalActionError` -- never silently coerced ... and never handled
differently because the seat happens to be human," and that translation
(plus the reject-and-reprompt-once policy) is explicitly ``Match``/CLI
territory (SLICES.md V3 step 2, tracked as KAN-1285), not this
``SeatController`` implementation's job. So this module does exactly two
things on a bad response: it never crashes on a raw stdlib exception
(``KeyError``/``TypeError``/``json.JSONDecodeError``) escaping out of
``decide()``, and it never silently invents a default action -- it raises
``ResponseParseError`` and stops, leaving translation to whatever calls it.
Likewise, ``legal_actions`` is advisory context sent to the model, not
something ``decide()`` re-validates its own return value against --
``SeatController``'s contract (``core/seat_controller.py``) already assigns
that enforcement to ``Match.submit_action``, unchanged by this ticket.

HTTP dependency: ``httpx2`` (PyPI, Pydantic's actively-maintained successor
to ``httpx``, API-compatible with it) -- already present transitively via
the ``mcp`` dependency (see ``uv.lock``), promoted to a direct dependency in
``pyproject.toml`` by this ticket so it isn't fragile to ``mcp``'s own
dependency tree changing later. The HTTP call itself goes through the
``client`` constructor parameter (an ``httpx2.Client``), never called
directly as a module-level function -- exactly the seam CLAUDE.md requires
("`OpenRouterBackend` (V3) and any live-API test must mock the HTTP call"):
tests inject an ``httpx2.Client`` wired to ``httpx2.MockTransport`` so no
unit test here ever opens a socket.
"""

from __future__ import annotations

import json
import os
from typing import Any, cast

import httpx2

from agent_game_framework.core.conversable import (
    ConversationInput,
    ConversationOutput,
    ConversationTurn,
    TextTurn,
)
from agent_game_framework.core.seat_controller import SeatDecision

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

_SYSTEM_PROMPT = (
    "You are one player's seat controller in a turn-based game. You will be "
    "given the current observation and the list of legal actions available "
    "to you. You must call the `submit_move` tool exactly once: choose "
    "`action` from the provided legal actions, and include a short (one "
    "sentence or less), in-character `banter` line about your move. Never "
    "call any tool other than `submit_move`, and never respond with plain "
    "text instead of a tool call."
)

_TOOL_NAME = "submit_move"

_CHAT_SYSTEM_PROMPT = (
    "You are one player in a turn-based game, chatting with your opponent -- "
    "this may happen between turns, mid-turn, or while you're deciding your "
    "own move; you have no way to tell which. Reply in character, "
    "conversationally, in one or two short sentences. This is a side "
    "conversation, not a move: never claim to make, take back, or announce a "
    "game action here, whatever your opponent says."
)


class ResponseParseError(Exception):
    """Raised when an OpenRouter chat-completions response can't be parsed
    into a legal-shaped ``(action, banter)`` pair.

    Deliberately **not** ``IllegalActionError``/``AgentTimeoutError``
    (ADR-0005) -- those are raised by ``Match``, never by a connector
    directly. This is the narrow, ``OpenRouterBackend``-specific exception
    that a future ``Match``/CLI reject-and-reprompt-once path (KAN-1285)
    catches and translates; ``OpenRouterBackend`` itself only ever raises
    this one type on a bad response, never a raw ``KeyError``/``TypeError``/
    ``json.JSONDecodeError``, and never returns a fabricated default action.
    """


class OpenRouterBackend[ObservationT, ActionT]:
    """A ``SeatController`` backed by an OpenRouter chat-completions call
    (``AgentBackend``, ADR-0005).

    Construct with a ``model`` string (whatever OpenRouter model slug you
    want, e.g. ``"openai/gpt-4o-mini"`` or ``"anthropic/claude-3.5-sonnet"``
    -- OpenRouter's own naming, this class does no validation of it) and
    either:

    - nothing else, in which case an ``httpx2.Client`` is built internally
      using ``api_key`` (or, if that's ``None`` too, the ``OPENROUTER_API_KEY``
      environment variable) for auth, and ``base_url`` (or, if that's
      ``None`` too, the ``OPENROUTER_BASE_URL`` environment variable, or
      ``_DEFAULT_BASE_URL`` if neither is set) for the endpoint; missing both
      the ``api_key`` and its environment fallback raises ``ValueError`` at
      construction time rather than failing confusingly on the first
      ``decide()`` call, or
    - an explicit ``client`` (an ``httpx2.Client``, e.g. one wired to
      ``httpx2.MockTransport`` in a test, or one you've pre-configured with
      your own auth/headers/base_url) -- when given, ``api_key`` is not
      required or consulted, since the client is assumed to already be fully
      configured for whatever transport it targets.

    This is the same testability pattern as ``RandomBotController``'s
    injectable ``rng`` and ``HumanCLIController``'s injectable
    ``input_fn``/``print_fn``: a real default for production use, an
    injectable seam for tests.

    Also implements ``Conversable`` (ADR-0008, ADR-0009) via ``respond()``: a
    second, independent chat-completions call -- plain, unconstrained free
    text, never the constrained ``submit_move`` tool call ``decide()`` uses
    -- so a human can converse with this seat without it ever being confused
    for, or confusing, an actual move.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        client: httpx2.Client | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        if client is not None:
            self._client = client
            return

        resolved_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY")
        if not resolved_key:
            raise ValueError(
                "OpenRouterBackend needs an OpenRouter API key: pass api_key=..., set "
                "the OPENROUTER_API_KEY environment variable (see .env.example), or "
                "pass a pre-configured client=... instead."
            )
        # base_url falls back to OPENROUTER_BASE_URL exactly the way api_key
        # falls back to OPENROUTER_API_KEY above -- additive and
        # backward-compatible, since nothing changes for any existing caller
        # when the env var isn't set (KAN-1287). This is the seam a
        # subprocess-based e2e test uses to point a real, installed `agf`
        # CLI process at a local mock HTTP server instead of the real
        # OpenRouter API: `client=...` (the seam every existing unit/
        # integration test uses via `httpx2.MockTransport`) only works
        # in-process, since `MockTransport` intercepts calls made by an
        # `httpx2.Client` living in the *same* Python process as the test --
        # it cannot see, let alone intercept, a real OS socket connection
        # opened by a separate subprocess. `cli.py`'s `build_controller`
        # constructs `OpenRouterBackend(model=model)` with no explicit
        # `client`/`base_url`, so an env-var override here is the only way
        # to redirect that subprocess's real HTTP client without touching
        # `cli.py` at all.
        resolved_base_url = (
            base_url
            if base_url is not None
            else os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_BASE_URL)
        )
        self._client = httpx2.Client(
            base_url=resolved_base_url,
            headers={
                "Authorization": f"Bearer {resolved_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def decide(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> SeatDecision[ActionT]:
        """Ask the model to choose one of ``legal_actions`` via a forced
        ``submit_move`` tool call, and parse its response.

        Sends one chat-completions request with ``tool_choice`` forcing the
        ``submit_move`` tool (see ``_build_request``), then hands the raw
        ``httpx2.Response`` to ``_parse_response``. Raises
        ``ResponseParseError`` -- never a raw stdlib exception, never a
        silently-invented action -- if the response can't be parsed into a
        legal-shaped ``(action, banter)`` pair. Does not itself check that
        the returned ``action`` is a member of ``legal_actions``; per
        ``SeatController``'s contract, that's advisory input here and
        ``Match``'s job to enforce.
        """
        payload = self._build_request(observation, legal_actions)
        response = self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        return self._parse_response(response)

    def respond(
        self, history: list[ConversationTurn], incoming: ConversationInput
    ) -> ConversationOutput:
        """``Conversable.respond`` (ADR-0008, ADR-0009): reply to ``incoming``
        given the conversation ``history`` so far, via a plain chat-
        completions call -- no tools, no forced tool_choice, unlike
        ``decide()``. ``history``'s ``"human"``/``"agent"`` roles map
        directly onto chat-completions ``"user"``/``"assistant"`` roles.

        Raises ``ResponseParseError`` -- never a raw stdlib exception -- on a
        response that isn't valid JSON, doesn't have the expected
        ``choices[0].message.content`` shape, or whose content isn't a
        string. Never called concurrently with itself for the same
        conversation history by this class -- ``LiveMatch`` (ADR-0009) is
        what serializes that, if a caller uses one; this method itself does
        no locking.
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": _CHAT_SYSTEM_PROMPT}]
        for turn in history:
            role = "user" if turn.role == "human" else "assistant"
            messages.append({"role": role, "content": turn.content.text})
        messages.append({"role": "user", "content": incoming.text})

        response = self._client.post(
            "/chat/completions", json={"model": self._model, "messages": messages}
        )
        response.raise_for_status()
        return self._parse_chat_response(response)

    def _parse_chat_response(self, response: httpx2.Response) -> ConversationOutput:
        """Parse a plain chat-completions response (``respond()``'s, never
        ``decide()``'s tool-call-shaped one) into a ``TextTurn``. Mirrors
        ``_parse_response``'s error handling exactly -- every failure mode
        (non-JSON body, missing ``choices``/``message``/``content``, a
        non-string ``content``) raises ``ResponseParseError`` rather than
        letting a raw ``KeyError``/``IndexError``/``TypeError``/
        ``json.JSONDecodeError`` escape."""
        try:
            data = response.json()
        except Exception as exc:
            raise ResponseParseError(
                f"OpenRouter response body was not valid JSON: {exc}"
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ResponseParseError(
                f"OpenRouter response did not match the expected chat-completion "
                f"shape: {exc!r} (response body: {data!r})"
            ) from exc

        if not isinstance(content, str):
            raise ResponseParseError(
                f"Chat-completion content must be a string, got "
                f"{type(content).__name__}: {content!r}"
            )
        return TextTurn(text=content)

    def _build_request(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> dict[str, Any]:
        """Build the OpenRouter/OpenAI-compatible chat-completions payload:
        the observation/legal actions as a user message, plus one
        constrained tool whose schema forces ``action`` to be one of
        ``legal_actions`` (a JSON-schema ``enum``) and ``banter`` to be a
        string, with ``tool_choice`` forcing that exact tool so the model
        cannot reply with plain text instead of a structured call.
        """
        user_content = json.dumps(
            {"observation": observation, "legal_actions": legal_actions}, default=str
        )
        tool = {
            "type": "function",
            "function": {
                "name": _TOOL_NAME,
                "description": (
                    "Submit your chosen action for this turn, plus a short "
                    "in-character banter line."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "description": (
                                "The chosen action. Must be exactly one of the "
                                "`legal_actions` given in the user message."
                            ),
                            "enum": legal_actions,
                        },
                        "banter": {
                            "type": "string",
                            "description": (
                                "A short (one sentence or less) in-character line "
                                "about this move."
                            ),
                        },
                    },
                    "required": ["action", "banter"],
                    "additionalProperties": False,
                },
            },
        }
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "tools": [tool],
            "tool_choice": {"type": "function", "function": {"name": _TOOL_NAME}},
        }

    def _parse_response(self, response: httpx2.Response) -> SeatDecision[ActionT]:
        """Parse a chat-completions HTTP response into a ``SeatDecision``.

        Walks ``choices[0].message.tool_calls[0].function.arguments`` (a
        JSON-encoded string per the OpenAI/OpenRouter tool-call contract),
        decodes it, and requires an ``action`` field (``banter`` defaults to
        ``None`` if the model omits it despite being asked for it -- a
        missing banter is a lesser sin than a missing move, and
        ``SeatDecision.banter`` already defaults to ``None``). Every
        failure mode -- a non-JSON body, a missing ``choices``/``message``/
        ``tool_calls``, non-JSON tool-call arguments, a non-object decoded
        result, a missing ``action``, or a non-string ``banter`` -- raises
        ``ResponseParseError`` with the offending value in the message,
        rather than letting the underlying ``KeyError``/``IndexError``/
        ``TypeError``/``json.JSONDecodeError`` escape uncaught.
        """
        try:
            data = response.json()
        except Exception as exc:
            raise ResponseParseError(
                f"OpenRouter response body was not valid JSON: {exc}"
            ) from exc

        try:
            message = data["choices"][0]["message"]
            tool_calls = message["tool_calls"]
            if not tool_calls:
                raise ResponseParseError(
                    f"OpenRouter response had no tool_calls (message: {message!r})"
                )
            raw_arguments = tool_calls[0]["function"]["arguments"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ResponseParseError(
                f"OpenRouter response did not match the expected tool-call shape: "
                f"{exc!r} (response body: {data!r})"
            ) from exc

        try:
            arguments = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ResponseParseError(
                f"Tool-call arguments were not valid JSON: {raw_arguments!r}"
            ) from exc

        if not isinstance(arguments, dict):
            raise ResponseParseError(
                f"Tool-call arguments decoded to a {type(arguments).__name__}, "
                f"expected a JSON object: {arguments!r}"
            )

        if "action" not in arguments:
            raise ResponseParseError(
                f"Tool-call arguments are missing the required 'action' field: {arguments!r}"
            )

        banter = arguments.get("banter")
        if banter is not None and not isinstance(banter, str):
            raise ResponseParseError(
                f"'banter' must be a string or absent, got {type(banter).__name__}: {banter!r}"
            )

        action = cast(ActionT, arguments["action"])
        return SeatDecision(action=action, banter=banter)
