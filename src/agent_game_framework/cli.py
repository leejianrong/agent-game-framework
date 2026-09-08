"""Command-line entry point for agent-game-framework (console script: ``agf``).

``agf --help``/``agf --version`` are the KAN-1274 package-skeleton behavior
and are unchanged here. This card (KAN-1279) adds the ``play`` subcommand:

    agf play tictactoe --seat X=human --seat O=bot:random [--json]

Per ADR-0006, this module is a *thin* adapter over ``Match``/``GameEngine``:
it parses ``--seat``/``--json``, drives one ``Match`` instance by repeatedly
calling ``current_players()``/``submit_action()``, and formats output -- it
never re-implements or re-checks game rules itself. Every legality decision
is left to ``Match.submit_action`` (which delegates to the engine's
``apply_action``); this module only reacts to the ``IllegalActionError`` it
may raise.

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
from agent_game_framework.agents import HumanCLIController, RandomBotController
from agent_game_framework.core import (
    GameEngine,
    IllegalActionError,
    Match,
    PlayerId,
    SeatController,
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


def build_controller(spec: str) -> SeatController[Any, Any]:
    """Build the ``SeatController`` named by one controller spec string.

    Supported specs today: ``"human"`` -> ``HumanCLIController`` (reads real
    stdin), ``"bot:random"`` -> ``RandomBotController`` (unseeded). Raises
    ``SeatSpecError`` for anything else -- LLM/algorithm specs (``llm:...``,
    ``algo:...``) are later tickets (V3/V4), not this one.
    """
    if spec == "human":
        return HumanCLIController()
    if spec == "bot:random":
        return RandomBotController()
    raise SeatSpecError(f"unknown controller spec {spec!r}; expected 'human' or 'bot:random'")


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
    seats: dict[PlayerId, SeatController[Any, Any]],
    *,
    game_name: str,
    json_mode: bool,
    print_fn: Callable[..., None] = print,
) -> None:
    """Drive ``match`` to completion, one seat decision at a time.

    For each player named by ``match.current_players()``, calls that seat's
    ``decide()`` and submits the resulting action via
    ``match.submit_action()``. This is the whole game loop -- no rule
    checking happens here (ADR-0006); ``Match``/the engine is the sole
    authority on legality.

    If ``submit_action`` raises ``IllegalActionError`` (a defensive path: in
    normal operation a well-behaved ``SeatController`` only ever returns an
    action from the ``legal_actions`` it was given, so this should not
    normally fire), the error is reported and the loop simply continues --
    since the match's internal state is unchanged on a raised
    ``IllegalActionError`` (see ``Match.submit_action``), the *same* player
    is still in ``current_players()`` on the next iteration, so that seat is
    asked to decide again rather than the turn silently advancing to anyone
    else or the whole match crashing.

    Turn output (rendered board or ``--json`` envelope) is only printed after
    a *successful* ``submit_action`` call.
    """
    while not match.is_terminal():
        for player in match.current_players():
            controller = seats[player]
            observation = match.observation_for(player)
            legal_actions = match.legal_actions(player)
            decision = controller.decide(observation, legal_actions)

            try:
                match.submit_action(player, decision.action)
            except IllegalActionError as exc:
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
                continue

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
        match: Match[Any, Any, Any] = Match(engine, players=order)
    except ValueError as exc:
        print_fn(f"Cannot start {args.game!r} with seats {order!r}: {exc}")
        return 2

    run_match(match, seats, game_name=args.game, json_mode=args.json, print_fn=print_fn)
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
            "'human' (reads stdin) or 'bot:random' (uniform-random moves)."
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
