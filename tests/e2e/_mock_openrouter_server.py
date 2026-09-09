"""Test-only, local HTTP server standing in for the real OpenRouter
chat-completions endpoint -- used by e2e tests that drive ``agf`` as a real
subprocess (KAN-1287, SLICES.md V3 "End-to-end" test plan). Like
``tests/e2e/_mcp_seeded_server.py`` (KAN-1283), this is test-only and never
shipped in ``src/``.

Why this exists instead of ``httpx2.MockTransport`` (the seam every existing
``OpenRouterBackend`` unit/integration test uses, e.g.
``tests/unit/test_openrouter_backend.py``): ``MockTransport`` only works
*in-process* -- it intercepts calls made by an ``httpx2.Client`` living in
the same Python process as the test. This ticket's e2e tests, per this
repo's established convention (``tests/e2e/test_cli_play.py``), must drive
the real, installed ``agf`` console script as a real subprocess
(``subprocess.run(["agf", "play", ...])``). ``OpenRouterBackend``, built
inside that separate subprocess by ``cli.py``'s ``build_controller``, then
makes a *real* HTTP connection attempt over an actual OS socket --
``MockTransport`` never leaves the test process, so it cannot intercept that
call at all, no matter how it's configured. Only a real, locally-bound HTTP
server the subprocess can actually connect to (via ``OPENROUTER_BASE_URL``,
KAN-1287's additive env-var override in ``OpenRouterBackend.__init__``) can
stand in for OpenRouter here. No new dependency is added to do this --
stdlib ``http.server`` is sufficient, keeping this repo's dependency surface
unchanged (still just ``mcp`` + ``httpx2``).

Design: robust rather than exactly-scripted. Pre-scripting an exact fixed
sequence of responses would be fragile -- a mismatch with the real game
state due to some timing/ordering assumption (e.g. "the LLM seat's second
call happens on turn 4") would break the test for reasons that have nothing
to do with what this ticket actually needs to prove. Instead, ``do_POST``
below handles *every* POST identically regardless of path -- no hardcoded
exact path match, mirroring how ``httpx2.MockTransport``'s handler in the
existing unit/integration tests ignores ``request.url`` too -- and always
replies with a legal move: it reads the request body, finds the forced
``submit_move`` tool's JSON-schema ``enum`` of legal actions (see
``OpenRouterBackend._build_request`` in ``openrouter.py`` for the exact
request shape this mirrors), and picks ``enum[0]``, the first legal action,
whatever it happens to be on that turn -- rather than a fixed pre-scripted
cell number. That makes this server correct regardless of what the other
seat (a human's scripted stdin, or a ``bot:random`` seat) has already done
to the board, with no fragile turn-order assumption baked in here.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

BANTER = "mocked LLM banter"
"""Fixed, assertable banter string every mocked response returns, so an e2e
test can assert on it without caring which turn produced it."""


class _Handler(BaseHTTPRequestHandler):
    """Answers every POST (any path) with a well-formed chat-completions
    tool-call response, mirroring the exact JSON shape used by
    ``tests/unit/test_openrouter_backend.py``'s ``_chat_completion_response``
    / ``tests/integration/test_match_agent_errors.py``'s
    ``_tool_call_response`` helpers -- ``OpenRouterBackend._parse_response``
    walks ``choices[0].message.tool_calls[0].function.arguments`` (a
    JSON-encoded string), so that's exactly what's built here.
    """

    def log_message(self, format: str, *args: Any) -> None:
        # BaseHTTPRequestHandler logs every request to stderr by default --
        # noisy in pytest output and irrelevant to what these tests assert.
        return

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        body = json.loads(raw_body) if raw_body else {}

        legal_actions = body["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
        chosen_action = legal_actions[0]

        arguments = json.dumps({"action": chosen_action, "banter": BANTER})
        response_body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "submit_move",
                                        "arguments": arguments,
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ).encode("utf-8")

        server = self.server
        if isinstance(server, MockOpenRouterServer):
            server.request_count += 1

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)


class MockOpenRouterServer(HTTPServer):
    """A local, ``127.0.0.1``-only stand-in for the OpenRouter chat-completions
    endpoint, used as a context manager so the background thread it serves
    from is always joined and its socket always closed, even if the test
    body raises -- never leaking a lingering thread/socket across tests.

    Binds to an OS-assigned free port (``0``) rather than a fixed one, so
    tests never fight over a port; the actual bound port is read back from
    ``server_address`` and exposed as ``base_url`` for a test to hand to the
    subprocess it drives via the ``OPENROUTER_BASE_URL`` environment
    variable. ``request_count`` lets a test assert the subprocess really did
    talk to this local mock (``>= 1``) rather than silently falling through
    to something else -- an extra guardrail on top of the structural
    guarantee that this server only ever binds to ``127.0.0.1``.

    Usage::

        with MockOpenRouterServer() as server:
            env = {**base_env, "OPENROUTER_BASE_URL": server.base_url}
            subprocess.run(["agf", "play", ...], env=env, ...)
            assert server.request_count >= 1
    """

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.request_count = 0
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self.server_address[0], self.server_address[1]
        return f"http://{host}:{port}"

    def __enter__(self) -> MockOpenRouterServer:
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.server_close()
