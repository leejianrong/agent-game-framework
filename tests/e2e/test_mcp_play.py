"""End-to-end test for the MCP connector (KAN-1283, SLICES.md V2 e2e test
plan, closing epic EPIC-181): "The test-only MCP client harness plays a full
game against a RandomBotController seat entirely over the MCP stdio
transport and reaches a terminal state matching what an equivalent
CLI-driven game would produce from the same random seed."

**Interpretation of "equivalent CLI-driven game" (a deliberate call, not an
oversight):** the CLI's ``--seat O=bot:random`` has no seeding knob --
``build_controller`` in ``cli.py`` always constructs an unseeded
``RandomBotController()`` -- and adding one is out of scope for this
MCP-focused ticket. Per ADR-0006, the CLI is *only* a thin translation layer
over ``Match`` (parses args, wires a seat map, calls
``Match.run_to_completion()``) with zero game-driving logic of its own. So
the faithful baseline this test compares against is a second ``Match``
built directly in-process -- same engine, same seeded
``RandomBotController`` for "O", the identical deterministic "always pick
the first legal action" policy for "X" that ``mcp_client_harness.py`` uses
over MCP -- driven via ``Match.run_to_completion()`` with a seat map,
*not* a second ``agf play`` subprocess. Actually shelling out to the CLI a
second time would only add subprocess noise (and require either an
unseeded, unreproducible bot or CLI changes out of this ticket's scope)
without changing what this test is actually meant to verify: that the
MCP-driven and directly-``Match``-driven code paths -- which per ADR-0006
share the exact same underlying ``Match``/``GameEngine`` orchestrator --
produce byte-identical results for identical inputs (same seed, same
policies). This is the same contract ADR-0006 makes for the CLI; this test
just proves it for MCP.

Real stdio subprocess, real MCP client transport (``mcp.stdio_client`` +
``mcp.ClientSession``, wrapped by ``mcp_client_harness.py``) -- unlike
``tests/integration/test_mcp_server.py``, which talks to the server
in-process via ``mcp.Client`` (see that module's docstring). This is the
first test in this repo to drive the MCP server over a real stdio pipe
rather than in-process.
"""

from __future__ import annotations

import asyncio
import random
import sys
from typing import Any

from agent_game_framework.agents import RandomBotController
from agent_game_framework.core import Match, SeatDecision
from examples.tictactoe import TicTacToeEngine
from tests.e2e.mcp_client_harness import play_full_game_as_seat_x

# Generous but bounded: a real subprocess spawn plus a full nine-tool-call-or-fewer
# game over stdio should finish in well under this on any CI runner; if the
# transport ever hangs (a broken pipe, a server that never replies), this
# turns that hang into a clear test failure instead of an indefinite stall --
# there is no repo-wide pytest-timeout plugin/marker configured for this
# (checked ``pyproject.toml``/``pytest.ini``/``conftest.py``), so this test
# adds its own bound directly via ``asyncio.wait_for``, the same way
# ``tests/e2e/test_cli_play.py``'s ``subprocess.run(..., timeout=...)`` bounds
# its own (synchronous) subprocess calls.
_E2E_TIMEOUT_SECONDS = 30.0

_SEED = 20260909


class _FirstLegalActionController:
    """The in-process baseline's seat "X" policy: always the first legal
    action -- the exact same deterministic rule
    ``mcp_client_harness.play_full_game_as_seat_x`` applies over MCP (see
    its docstring). Kept here, not imported from ``mcp_client_harness``,
    because the two are different kinds of thing: this is a real
    ``SeatController`` plugged into ``Match.run_to_completion()``'s seat
    map, while the harness's rule lives inline in an MCP tool-call loop --
    there is no shared abstraction to factor out beyond "pick
    ``legal_actions[0]``", so this docstring is what keeps the two policies
    honestly in sync instead of a shared helper.
    """

    def decide(self, observation: Any, legal_actions: list[int]) -> SeatDecision[int]:
        return SeatDecision(action=legal_actions[0], banter=None)


def _run_in_process_baseline(seed: int) -> dict[str, Any]:
    """Build and drive the "equivalent" game directly against ``Match`` --
    see the module docstring for why this, not a second CLI subprocess, is
    the right baseline for this test.
    """
    match: Match[Any, Any, Any] = Match(
        TicTacToeEngine(),
        players=["X", "O"],
        seats={
            "X": _FirstLegalActionController(),
            "O": RandomBotController(random.Random(seed)),
        },
    )
    match.run_to_completion()
    return match.serialize()


def test_mcp_harness_full_game_matches_in_process_baseline_for_same_seed() -> None:
    """Same seed, same seat policies, two different drivers (real MCP stdio
    subprocess vs. direct ``Match.run_to_completion()``) -- final serialized
    state (board + whose turn index, which pins down the winner/draw
    outcome) must match exactly.
    """
    mcp_final_state = asyncio.run(
        asyncio.wait_for(
            play_full_game_as_seat_x(sys.executable, _SEED),
            timeout=_E2E_TIMEOUT_SECONDS,
        )
    )

    baseline_final_state = _run_in_process_baseline(_SEED)

    assert mcp_final_state == baseline_final_state
