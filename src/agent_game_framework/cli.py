"""Command-line entry point for agent-game-framework (console script: ``agf``).

``agf --help``/``agf --version`` are the KAN-1274 package-skeleton behavior
and are unchanged here. The ``play`` subcommand (KAN-1279, turn-loop
mechanics moved into ``Match`` by KAN-1280):

    agf play tictactoe --seat X=human --seat O=bot:random [--json]

Per ADR-0006, this module is a *thin* adapter over ``Match``/``GameEngine``:
it parses ``--seat``/``--json``, builds a seat -> ``SeatController`` mapping
and hands it to ``Match`` (which owns turn-loop mechanics, PLAN.md Shape S2),
and formats output via the ``on_turn``/``on_illegal_action`` hooks
``Match.run_to_completion`` calls back into -- it never re-implements or
re-checks game rules itself. Every legality decision is left to
``Match.submit_action`` (which delegates to the engine's ``apply_action``);
this module only reacts to the ``IllegalActionError`` ``Match`` surfaces via
``on_illegal_action``. A match with zero human seats (all ``bot:random``)
drives through this exact same code path as a mixed human/bot match -- "how
many humans" is only a difference in which controllers land in the seat map
handed to ``Match``, per R1/ADR-0005.

``cmd_play`` also catches ``AgentTimeoutError`` (SLICES.md V3 step 2,
KAN-1285): a seat's controller (e.g. an ``OpenRouterBackend`` seeing a
network timeout, or twice failing to produce a parseable response) that
failed entirely to produce a decision, even after ``Match``'s internal
reject-and-reprompt-once retry. Reported via ``print_fn`` with a non-zero
exit code, the same as this module's other pre-existing usage/construction
error paths -- never a raw, uncaught traceback.

Only Tic-Tac-Toe (``examples.tictactoe``, KAN-1277) is registered as a
playable game for now -- see ``GAME_REGISTRY``. That engine lives outside
``src/`` per ADR-0001 (a throwaway reference implementation, not part of the
installable package/wheel), so ``GAME_REGISTRY``'s factory for it imports
``examples.tictactoe`` lazily (only when ``agf play tictactoe`` actually
runs) rather than at module import time -- ``examples/`` is on ``sys.path``
alongside the checked-out repo for ``uv run``/pytest in this dev repo, but
*not* for a plain installed console script with no such checkout nearby, and
``agf --help``/``--version``/no-subcommand must keep working regardless (see
``tests/e2e/test_cli_help.py``). See the PR description / KAN-1280 friction
notes for the follow-up this implies once a *real* second game replaces the
throwaway one.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from agent_game_framework import __version__
from agent_game_framework.agents import HumanCLIController, OpenRouterBackend, RandomBotController
from agent_game_framework.core import (
    AgentTimeoutError,
    GameEngine,
    IllegalActionError,
    Match,
    PlayerId,
    SeatController,
    SeatDecision,
)

GameFactory = Callable[[], GameEngine[Any, Any, Any]]


def _make_tictactoe_engine() -> GameEngine[Any, Any, Any]:
    """Import and build ``TicTacToeEngine`` lazily -- see the module
    docstring for why this import must not happen at module load time."""
    from examples.tictactoe import TicTacToeEngine

    return TicTacToeEngine()


GAME_REGISTRY: dict[str, GameFactory] = {
    "tictactoe": _make_tictactoe_engine,
}
"""Game name (as used on the ``agf play <game>`` command line) -> a
zero-argument factory returning a fresh ``GameEngine`` instance.

A small dict, not a plugin system -- deliberately, per this ticket's scope
(only one game exists today). Add an entry here when a second game lands.
"""


class SeatSpecError(ValueError):
    """A ``--seat`` argument's syntax or controller spec is invalid.

    Raised by CLI-layer parsing only (``parse_seat_arg``/``build_controller``)
    -- never by game-rule checks, which stay ``Match``/``GameEngine``'s job.
    """


def parse_seat_arg(raw: str) -> tuple[PlayerId, str]:
    """Split one ``--seat`` value into ``(player_id, controller_spec)``.

    Expected form: ``<id>=<controller-spec>``, e.g. ``"X=human"`` or
    ``"O=bot:random"``. Raises ``SeatSpecError`` if ``raw`` has no ``=``, or
    an empty id or spec on either side of it.
    """
    if "=" not in raw:
        raise SeatSpecError(
            f"--seat value {raw!r} must be of the form <id>=<controller-spec> "
            "(e.g. X=human or O=bot:random)"
        )
    player_id, _, spec = raw.partition("=")
    if not player_id:
        raise SeatSpecError(f"--seat value {raw!r} is missing a seat id before '='")
    if not spec:
        raise SeatSpecError(f"--seat value {raw!r} is missing a controller spec after '='")
    return player_id, spec


_OPENROUTER_PREFIX = "llm:openrouter/"
"""Fixed prefix stripped from an ``llm:openrouter/<model>`` spec to recover
the OpenRouter model slug. Deliberately a prefix strip, not a split on the
first ``/`` -- OpenRouter model slugs themselves routinely contain a ``/``
(e.g. ``openai/gpt-4o-mini``, ``anthropic/claude-3.5-sonnet``), so splitting
on the first ``/`` would chop the provider half off the model slug."""


def build_controller(spec: str) -> SeatController[Any, Any]:
    """Build the ``SeatController`` named by one controller spec string.

    Supported specs today: ``"human"`` -> ``HumanCLIController`` (reads real
    stdin), ``"bot:random"`` -> ``RandomBotController`` (unseeded),
    ``"llm:openrouter/<model>"`` -> ``OpenRouterBackend(model=<model>)``
    (SLICES.md V3 step 3, KAN-1286) -- everything after the fixed
    ``"llm:openrouter/"`` prefix is passed through verbatim as the model
    slug, including any further ``/`` it contains (see ``_OPENROUTER_PREFIX``).
    Algorithm specs (``algo:...``, and composite ``advised-by=``/
    ``narrated-by=`` modifiers) are a later ticket (V4), not this one.

    Raises ``SeatSpecError`` for: an empty model after the ``llm:openrouter/``
    prefix (``"llm:openrouter/"`` with nothing after it); an ``llm:`` spec
    naming any other provider (only ``openrouter`` is supported right now --
    reported with a specific message rather than falling through to the
    generic "unknown controller spec" one); a missing/unresolvable
    ``OPENROUTER_API_KEY`` (``OpenRouterBackend.__init__`` raises a plain
    ``ValueError`` for this -- wrapped into ``SeatSpecError`` here so
    ``cmd_play``'s single existing ``except SeatSpecError`` catch site is
    still the one place every ``--seat`` construction error surfaces, rather
    than a raw ``ValueError`` escaping and crashing the CLI); or any other
    unrecognized spec entirely.
    """
    if spec == "human":
        return HumanCLIController()
    if spec == "bot:random":
        return RandomBotController()
    if spec.startswith(_OPENROUTER_PREFIX):
        model = spec[len(_OPENROUTER_PREFIX) :]
        if not model:
            raise SeatSpecError(
                f"--seat spec {spec!r} is missing a model after 'llm:openrouter/' "
                "(e.g. llm:openrouter/openai/gpt-4o-mini)"
            )
        try:
            return OpenRouterBackend(model=model)
        except ValueError as exc:
            raise SeatSpecError(
                f"cannot build llm:openrouter controller for spec {spec!r}: {exc}"
            ) from exc
    if spec.startswith("llm:"):
        raise SeatSpecError(
            f"unsupported llm provider in spec {spec!r}; only 'llm:openrouter/<model>' "
            "is supported right now"
        )
    raise SeatSpecError(
        f"unknown controller spec {spec!r}; expected 'human', 'bot:random', or "
        "'llm:openrouter/<model>'"
    )


def render_tictactoe_board(board: list[PlayerId | None]) -> str:
    """Render a 9-cell row-major Tic-Tac-Toe ``board`` (from ``observation["board"]``
    or ``Match.serialize()["board"]``) as a 3x3 human-readable grid, e.g.::

        X | O | .
        ---------
        . | X | .
        ---------
        . | . | O

    Empty cells (``None``) render as ``.``. Purely a presentation helper --
    it derives everything from the board it is given and never judges
    legality or game-over status itself (ADR-0006).
    """

    def cell(index: int) -> str:
        mark = board[index]
        return mark if mark is not None else "."

    rows = [" | ".join(cell(row * 3 + col) for col in range(3)) for row in range(3)]
    separator = "-" * len(rows[0])
    return f"\n{separator}\n".join(rows)


def run_match(
    match: Match[Any, Any, Any],
    *,
    game_name: str,
    json_mode: bool,
    print_fn: Callable[..., None] = print,
) -> None:
    """Drive ``match`` to completion, formatting output as each turn resolves.

    ``match`` must already have been constructed with its seat map (``Match(
    ..., seats=...)``, KAN-1280) -- turn-loop mechanics (asking
    ``current_players()``'s seats to ``decide()``, submitting the result)
    live entirely in ``Match.run_to_completion``/``Match.play_turn`` now
    (PLAN.md Shape S2); this function only supplies the ``on_turn``/
    ``on_illegal_action`` hooks that turn a resolved turn into CLI output --
    no rule checking happens here (ADR-0006), and this module never drives
    the loop itself. A zero-human-seat (all-bot) match and a mixed
    human/bot match both flow through this exact same call (R1).

    If ``submit_action`` raises ``IllegalActionError`` (a defensive path: in
    normal operation a well-behaved ``SeatController`` only ever returns an
    action from the ``legal_actions`` it was given, so this should not
    normally fire), ``on_illegal_action`` reports it and ``Match`` continues
    the loop -- since the match's internal state is unchanged on a raised
    ``IllegalActionError`` (see ``Match.submit_action``), the *same* player
    is still in ``current_players()`` on the next round, so that seat is
    asked to decide again rather than the turn silently advancing to anyone
    else or the whole match crashing.

    Turn output (rendered board or ``--json`` envelope) is only printed after
    a *successful* ``submit_action`` call.

    ``Match.run_to_completion`` may also raise ``AgentTimeoutError``
    (SLICES.md V3 step 2, KAN-1285): a seat's controller failed to produce a
    decision at all -- twice in a row, after ``Match``'s internal
    reject-and-reprompt-once retry -- rather than returning a
    well-formed-but-illegal action. This function deliberately does **not**
    catch it here; it propagates to ``cmd_play``, which is where every other
    match-ending/usage-error message in this module is decided (unknown
    game, bad ``--seat`` spec) and where the process's exit code is chosen.
    """

    def on_turn(player: PlayerId, decision: SeatDecision[Any]) -> None:
        if json_mode:
            print_fn(
                json.dumps(
                    {
                        "type": "turn",
                        "seat": player,
                        "action": decision.action,
                        "banter": decision.banter,
                        "state": match.serialize(),
                    }
                )
            )
        else:
            banter_suffix = f'  ("{decision.banter}")' if decision.banter else ""
            print_fn(f"{player} plays {decision.action!r}{banter_suffix}")
            if game_name == "tictactoe":
                print_fn(render_tictactoe_board(match.observation_for(player)["board"]))
            print_fn()

    def on_illegal_action(
        player: PlayerId, decision: SeatDecision[Any], exc: IllegalActionError
    ) -> None:
        if json_mode:
            print_fn(
                json.dumps(
                    {
                        "type": "illegal_action",
                        "seat": player,
                        "action": decision.action,
                        "error": str(exc),
                    }
                )
            )
        else:
            print_fn(f"Illegal move by {player}: {exc} -- {player} to move again.")

    match.run_to_completion(on_turn=on_turn, on_illegal_action=on_illegal_action)

    winners = match.winners()
    if json_mode:
        print_fn(json.dumps({"type": "result", "winners": winners, "state": match.serialize()}))
    elif winners:
        print_fn(f"Game over. Winner(s): {', '.join(winners)}")
    else:
        print_fn("Game over. Draw.")


def cmd_play(args: argparse.Namespace, *, print_fn: Callable[..., None] = print) -> int:
    """Handle ``agf play <game> --seat ... [--json]``.

    Parses ``--seat`` args and builds a controller per seat, constructs one
    ``Match`` over the named game's engine, and hands both to ``run_match``.
    Any ``--seat``/game-construction problem is reported and exits non-zero
    *before* the match starts -- it is a CLI-usage error, not a game-rule
    one.

    If ``run_match`` propagates ``AgentTimeoutError`` (a seat's controller
    failed twice in a row to produce a decision at all, SLICES.md V3 step 2,
    KAN-1285), this is caught here -- the same category of failure this
    function already guards against for ``SeatSpecError``/unknown-game/
    ``ValueError`` at match construction -- and reported via ``print_fn``
    (a JSON ``"agent_error"`` envelope in ``--json`` mode, matching the
    style of ``run_match``'s ``"illegal_action"``/``"result"`` envelopes;
    plain text otherwise) with a non-zero exit code, instead of letting a
    raw traceback crash the CLI mid-game.
    """
    if args.game not in GAME_REGISTRY:
        print_fn(f"Unknown game {args.game!r}; available games: {sorted(GAME_REGISTRY)}")
        return 1

    if not args.seat:
        print_fn("At least one --seat <id>=<controller-spec> is required.")
        return 2

    seats: dict[PlayerId, SeatController[Any, Any]] = {}
    order: list[PlayerId] = []
    for raw in args.seat:
        try:
            player_id, spec = parse_seat_arg(raw)
            controller = build_controller(spec)
        except SeatSpecError as exc:
            print_fn(f"Invalid --seat argument: {exc}")
            return 2
        if player_id in seats:
            print_fn(f"Invalid --seat argument: duplicate seat id {player_id!r}")
            return 2
        seats[player_id] = controller
        order.append(player_id)

    engine = GAME_REGISTRY[args.game]()
    try:
        match: Match[Any, Any, Any] = Match(engine, players=order, seats=seats)
    except ValueError as exc:
        print_fn(f"Cannot start {args.game!r} with seats {order!r}: {exc}")
        return 2

    try:
        run_match(match, game_name=args.game, json_mode=args.json, print_fn=print_fn)
    except AgentTimeoutError as exc:
        if args.json:
            print_fn(json.dumps({"type": "agent_error", "error": str(exc)}))
        else:
            print_fn(f"Agent seat failed to respond: {exc}")
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="agf",
        description="agent-game-framework CLI.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    play_parser = subparsers.add_parser(
        "play",
        help="Play a game, seat by seat, to completion.",
        description=(
            "Play <game> to completion. Supply one --seat <id>=<controller-spec> "
            "per seat (an arbitrary number, in turn order); controller specs: "
            "'human' (reads stdin), 'bot:random' (uniform-random moves), or "
            "'llm:openrouter/<model>' (an OpenRouterBackend seat, e.g. "
            "llm:openrouter/openai/gpt-4o-mini; needs OPENROUTER_API_KEY set)."
        ),
    )
    play_parser.add_argument(
        "game",
        choices=sorted(GAME_REGISTRY),
        help="Game to play.",
    )
    play_parser.add_argument(
        "--seat",
        action="append",
        default=[],
        metavar="<id>=<controller-spec>",
        dest="seat",
        help="Seat assignment, e.g. X=human or O=bot:random. Repeatable, in turn order.",
    )
    play_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one JSON object per turn (and a final result) instead of a rendered board.",
    )
    play_parser.set_defaults(func=cmd_play)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``agf`` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None:
        return 0
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
