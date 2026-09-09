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
      environment variable) for auth; missing both raises ``ValueError`` at
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
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        client: httpx2.Client | None = None,
        base_url: str = _DEFAULT_BASE_URL,
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
        self._client = httpx2.Client(
            base_url=base_url,
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
