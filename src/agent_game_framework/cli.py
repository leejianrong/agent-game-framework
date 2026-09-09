"""Command-line entry point for agent-game-framework (console script: ``agf``).

``agf --help``/``agf --version`` are the KAN-1274 package-skeleton behavior
and are unchanged here. The ``play`` subcommand (KAN-1279, turn-loop
mechanics moved into ``Match`` by KAN-1280):

    agf play tictactoe --seat X=human --seat O=bot:random [--json]

A ``--seat`` spec may also carry an ``:advised-by=algo:<name>`` or
``:narrated-by=<controller-spec>`` modifier suffix (SLICES.md V4 step 5,
KAN-1291), composing a base spec + an ``algo:<name>`` algorithm spec into an
``AdvisedLLMSeatController``/``AutoplayNarratorSeatController`` (ADR-0004),
e.g.::

    agf play tictactoe \\
      --seat X=llm:openrouter/openai/gpt-4o-mini:advised-by=algo:tictactoe-minimax \\
      --seat O=algo:tictactoe-minimax:narrated-by=llm:openrouter/openai/gpt-4o-mini

The plain, unadvised ``--seat=llm:openrouter/<model>`` form from V3 keeps
working completely unchanged -- see ``build_controller``.

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
runs) rather than at module import time. Neither the installed ``agf``
console script nor ``uv run agf``/``uv run python -m ...`` put the repo root
on ``sys.path`` automatically the way pytest's own ``pythonpath = ["."]`` ini
setting does -- only ``python -m agent_game_framework.cli`` gets that for
free, because ``-m`` adds the current directory itself. ``_ensure_examples_
importable`` below closes that gap for the other two invocation styles when
run from this checked-out repo (a no-op, falling through to the ordinary
``ModuleNotFoundError``, when there is no such checkout nearby -- e.g. a real
install in a sibling game repo, per ADR-0001). ``agf --help``/``--version``/
no-subcommand must keep working regardless of any of this (see
``tests/e2e/test_cli_help.py``). See the PR description / KAN-1280 friction
notes for the follow-up this implies once a *real* second game replaces the
throwaway one.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import queue
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_game_framework import __version__
from agent_game_framework.agents import HumanCLIController, OpenRouterBackend, RandomBotController
from agent_game_framework.algorithm import (
    AdvisedLLMSeatController,
    AutoplayNarratorSeatController,
    GameAlgorithm,
)
from agent_game_framework.core import (
    AgentTimeoutError,
    Conversable,
    GameEngine,
    IllegalActionError,
    LiveMatch,
    Match,
    PlayerId,
    SeatController,
    SeatDecision,
)

GameFactory = Callable[[], GameEngine[Any, Any, Any]]
AlgorithmFactory = Callable[[], GameAlgorithm[Any, Any]]
RendererFactory = Callable[[], Callable[[dict[str, Any]], str]]


def _ensure_examples_importable() -> None:
    """Put this checked-out repo's root on ``sys.path`` if that's what it
    takes to make ``examples`` importable (see the module docstring). A
    no-op when ``examples`` already resolves (pytest, ``python -m``) or when
    there is no ``examples/`` next to this installed copy of the package to
    find (a real install with no dev checkout nearby, per ADR-0001) --
    either way, the caller's own ``from examples... import ...`` is left to
    succeed or raise ``ModuleNotFoundError`` normally."""
    if importlib.util.find_spec("examples") is not None:
        return
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / "examples").is_dir() and str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _make_tictactoe_engine() -> GameEngine[Any, Any, Any]:
    """Import and build ``TicTacToeEngine`` lazily -- see the module
    docstring for why this import must not happen at module load time."""
    _ensure_examples_importable()
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


def _make_tictactoe_minimax_algorithm() -> GameAlgorithm[Any, Any]:
    """Import and build ``TicTacToeMinimaxAlgorithm`` lazily -- same reasoning
    as ``_make_tictactoe_engine``: ``examples/`` isn't on ``sys.path`` for a
    plain installed console script with no repo checkout nearby."""
    _ensure_examples_importable()
    from examples.tictactoe.algorithm.minimax import TicTacToeMinimaxAlgorithm

    return TicTacToeMinimaxAlgorithm()


ALGORITHM_REGISTRY: dict[str, AlgorithmFactory] = {
    "tictactoe-minimax": _make_tictactoe_minimax_algorithm,
}
"""``algo:<name>`` name (as used in a ``--seat`` spec's ``advised-by=``/
``narrated-by=`` modifier, e.g. ``algo:tictactoe-minimax``) -> a
zero-argument factory returning a fresh ``GameAlgorithm`` instance.

Mirrors ``GAME_REGISTRY``'s exact shape/reasoning (SLICES.md V4 step 5,
KAN-1291) -- a small dict, not a plugin system, one entry per algorithm that
exists today. There is deliberately no *bare* ``algo:...`` seat spec (a
standalone algorithm-only bot with no LLM at all) wired up in
``build_controller`` -- ADR-0004 calls that a "trivial degenerate case," but
no ticket has built the ``AlgorithmSeatController`` class it would need, and
this ticket's demo/test plan only exercises the two composite forms
(``advised-by=``/``narrated-by=``). ``build_algorithm``'s only caller is the
modifier-parsing logic inside ``build_controller``.
"""


def _make_tictactoe_renderer() -> Callable[[dict[str, Any]], str]:
    """Import and return Tic-Tac-Toe's own board-rendering function lazily --
    same reasoning as ``_make_tictactoe_engine``."""
    _ensure_examples_importable()
    from examples.tictactoe.cli_render import render_observation

    return render_observation


RENDERER_REGISTRY: dict[str, RendererFactory] = {
    "tictactoe": _make_tictactoe_renderer,
}
"""Game name -> a zero-argument factory returning a function that renders one
``observation_for(...)``-shaped dict as a human-readable string.

Optional per game (``run_match``/``cmd_play`` fall back to printing nothing
extra beyond the plain ``"<player> plays <action>"`` line when a game has no
entry here) -- this is what keeps the framework's CLI itself from ever
needing to know a specific game's board shape (ADR-0001, ADR-0006): a game
that wants a nicer rendering supplies its own renderer here, the same way it
supplies its own ``GameEngine``/``GameAlgorithm`` via ``GAME_REGISTRY``/
``ALGORITHM_REGISTRY``, instead of this module branching on the game's name
(as it used to, via a hardcoded ``if game_name == "tictactoe"`` calling a
``render_tictactoe_board`` that lived right here) to decide how to draw its
board.
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

_ALGO_PREFIX = "algo:"
"""Fixed prefix an algorithm spec (e.g. ``algo:tictactoe-minimax``) must
start with -- see ``build_algorithm``."""

_ADVISED_BY_SEP = ":advised-by="
"""Literal substring marking an ``:advised-by=<algo-spec>`` modifier suffix
on a ``--seat`` spec, e.g.
``"llm:openrouter/openai/gpt-4o-mini:advised-by=algo:tictactoe-minimax"``.
Composes into an ``AdvisedLLMSeatController`` -- see ``build_controller``."""

_NARRATED_BY_SEP = ":narrated-by="
"""Literal substring marking a ``:narrated-by=<controller-spec>`` modifier
suffix on a ``--seat`` spec, e.g.
``"algo:tictactoe-minimax:narrated-by=llm:openrouter/openai/gpt-4o-mini"``.
Composes into an ``AutoplayNarratorSeatController`` -- see
``build_controller``."""


def build_algorithm(spec: str) -> GameAlgorithm[Any, Any]:
    """Build the ``GameAlgorithm`` named by one ``algo:<name>`` spec string
    (SLICES.md V4 step 5, KAN-1291).

    Mirrors ``build_controller``'s exact shape: strips the required
    ``"algo:"`` prefix, looks the remainder up in ``ALGORITHM_REGISTRY``, and
    raises ``SeatSpecError`` -- the one exception type every spec-parsing
    error in this module raises -- for a missing prefix or an unknown name.

    This is only ever called from ``build_controller``'s modifier-parsing
    logic (the ``:advised-by=``/``:narrated-by=`` suffixes) -- there is no
    top-level, bare ``algo:...`` seat spec wired up (see
    ``ALGORITHM_REGISTRY``'s docstring for why).
    """
    if not spec.startswith(_ALGO_PREFIX):
        raise SeatSpecError(
            f"algorithm spec {spec!r} must start with 'algo:' (e.g. 'algo:tictactoe-minimax')"
        )
    name = spec[len(_ALGO_PREFIX) :]
    factory = ALGORITHM_REGISTRY.get(name)
    if factory is None:
        raise SeatSpecError(
            f"unknown algorithm {name!r} in spec {spec!r}; available algorithms: "
            f"{sorted(ALGORITHM_REGISTRY)}"
        )
    return factory()


def build_controller(spec: str) -> SeatController[Any, Any]:
    """Build the ``SeatController`` named by one controller spec string.

    Supported specs today: ``"human"`` -> ``HumanCLIController`` (reads real
    stdin), ``"bot:random"`` -> ``RandomBotController`` (unseeded),
    ``"llm:openrouter/<model>"`` -> ``OpenRouterBackend(model=<model>)``
    (SLICES.md V3 step 3, KAN-1286) -- everything after the fixed
    ``"llm:openrouter/"`` prefix is passed through verbatim as the model
    slug, including any further ``/`` it contains (see ``_OPENROUTER_PREFIX``).

    Also supported (SLICES.md V4 step 5, KAN-1291): a spec carrying an
    ``:advised-by=<algo-spec>`` or ``:narrated-by=<controller-spec>``
    modifier suffix, composing a base spec with a modifier value into one of
    the two framework-provided composite controllers (ADR-0004):

    - ``"<base>:advised-by=<algo-spec>"`` -> ``AdvisedLLMSeatController(llm=
      build_controller(base), algorithm=build_algorithm(algo_spec))``, e.g.
      ``"llm:openrouter/openai/gpt-4o-mini:advised-by=algo:tictactoe-minimax"``.
    - ``"<algo-spec>:narrated-by=<controller-spec>"`` -> ``AutoplayNarratorSeatController(
      algorithm=build_algorithm(algo_spec), narrator_llm=build_controller(controller_spec))``,
      e.g. ``"algo:tictactoe-minimax:narrated-by=llm:openrouter/openai/gpt-4o-mini"``.

    Modifier detection happens **before** any of the plain-spec checks below
    -- this is the one subtlety to preserve here: since an ``llm:openrouter/``
    model slug can itself contain arbitrary characters (only the fixed
    prefix is stripped, see ``_OPENROUTER_PREFIX``), an
    ``:advised-by=``/``:narrated-by=`` suffix must be split off *before* that
    branch runs, or the entire modifier would be swallowed into the model
    slug instead of being recognized as a modifier. A spec is never expected
    to carry both suffixes; whichever literal substring is found first
    (``:advised-by=`` checked first) determines which composite is built --
    the base/modifier spec on either side of it is resolved generically, via
    a recursive call to this same function (for a ``SeatController``) or to
    ``build_algorithm`` (for a ``GameAlgorithm``), so *any* spec that
    resolves to the right kind of thing composes, not just an ``llm:`` base
    or an ``algo:`` modifier specifically.

    A *bare* ``algo:...`` spec (no modifier) is intentionally unsupported --
    see ``ALGORITHM_REGISTRY``'s docstring.

    Raises ``SeatSpecError`` for: an empty model after the ``llm:openrouter/``
    prefix (``"llm:openrouter/"`` with nothing after it); an ``llm:`` spec
    naming any other provider (only ``openrouter`` is supported right now --
    reported with a specific message rather than falling through to the
    generic "unknown controller spec" one); a missing/unresolvable
    ``OPENROUTER_API_KEY`` (``OpenRouterBackend.__init__`` raises a plain
    ``ValueError`` for this -- wrapped into ``SeatSpecError`` here so
    ``cmd_play``'s single existing ``except SeatSpecError`` catch site is
    still the one place every ``--seat`` construction error surfaces, rather
    than a raw ``ValueError`` escaping and crashing the CLI); an empty base
    or modifier half of an ``:advised-by=``/``:narrated-by=`` spec; an
    unresolvable base/modifier spec nested inside one (an unknown algorithm
    name, a bad nested controller spec -- ``build_algorithm``/the recursive
    call to this function already raise ``SeatSpecError`` for those, so no
    extra wrapping is needed here); or any other unrecognized spec entirely.
    """
    if _ADVISED_BY_SEP in spec:
        base_spec, _, modifier_spec = spec.partition(_ADVISED_BY_SEP)
        if not base_spec or not modifier_spec:
            raise SeatSpecError(
                f"--seat spec {spec!r} is missing a base or algorithm spec around "
                "':advised-by=' (e.g. "
                "'llm:openrouter/openai/gpt-4o-mini:advised-by=algo:tictactoe-minimax')"
            )
        llm = build_controller(base_spec)
        algorithm = build_algorithm(modifier_spec)
        return AdvisedLLMSeatController(llm=llm, algorithm=algorithm)
    if _NARRATED_BY_SEP in spec:
        base_spec, _, modifier_spec = spec.partition(_NARRATED_BY_SEP)
        if not base_spec or not modifier_spec:
            raise SeatSpecError(
                f"--seat spec {spec!r} is missing an algorithm or narrator spec around "
                "':narrated-by=' (e.g. "
                "'algo:tictactoe-minimax:narrated-by=llm:openrouter/openai/gpt-4o-mini')"
            )
        algorithm = build_algorithm(base_spec)
        narrator_llm = build_controller(modifier_spec)
        return AutoplayNarratorSeatController(algorithm=algorithm, narrator_llm=narrator_llm)

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
        f"unknown controller spec {spec!r}; expected 'human', 'bot:random', "
        "'llm:openrouter/<model>', or a composite '<spec>:advised-by=algo:<name>'/"
        "'algo:<name>:narrated-by=<spec>'"
    )


def _make_turn_hooks(
    match: Match[Any, Any, Any],
    *,
    json_mode: bool,
    renderer: Callable[[dict[str, Any]], str] | None,
    print_fn: Callable[..., None],
) -> tuple[
    Callable[[PlayerId, SeatDecision[Any]], None],
    Callable[[PlayerId, SeatDecision[Any], IllegalActionError], None],
]:
    """Build the ``on_turn``/``on_illegal_action`` hooks ``run_match`` hands
    to ``Match.run_to_completion`` -- factored out so ``run_live_match_with_chat``
    (ADR-0009) can hand the exact same rendering/JSON-envelope behavior to
    ``LiveMatch`` instead, with zero duplicated presentation logic between the
    synchronous and background-thread turn-driving paths.
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
            if renderer is not None:
                print_fn(renderer(match.observation_for(player)))
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

    return on_turn, on_illegal_action


def _print_result(
    match: Match[Any, Any, Any], *, json_mode: bool, print_fn: Callable[..., None]
) -> None:
    """Print the final ``"Game over."``/``--json`` ``"result"`` line -- the
    tail end shared by ``run_match`` and ``run_live_match_with_chat``."""
    winners = match.winners()
    if json_mode:
        print_fn(json.dumps({"type": "result", "winners": winners, "state": match.serialize()}))
    elif winners:
        print_fn(f"Game over. Winner(s): {', '.join(winners)}")
    else:
        print_fn("Game over. Draw.")


def run_match(
    match: Match[Any, Any, Any],
    *,
    json_mode: bool,
    renderer: Callable[[dict[str, Any]], str] | None = None,
    print_fn: Callable[..., None] = print,
) -> int:
    """Drive ``match`` to completion, formatting output as each turn resolves.
    Always returns ``0`` -- the return value exists so this function and
    ``run_live_match_with_chat`` share one result-code shape for
    ``cmd_play`` to return as the process's exit code.

    ``match`` must already have been constructed with its seat map (``Match(
    ..., seats=...)``, KAN-1280) -- turn-loop mechanics (asking
    ``current_players()``'s seats to ``decide()``, submitting the result)
    live entirely in ``Match.run_to_completion``/``Match.play_turn`` now
    (PLAN.md Shape S2); this function only supplies the ``on_turn``/
    ``on_illegal_action`` hooks that turn a resolved turn into CLI output --
    no rule checking happens here (ADR-0006), and this module never drives
    the loop itself. A zero-human-seat (all-bot) match and a mixed
    human/bot match both flow through this exact same call (R1).

    ``renderer``, if given (looked up by the caller from
    ``RENDERER_REGISTRY`` for the game being played), is called with the
    acting player's ``observation_for(...)`` after each successful turn to
    print a human-readable board alongside the plain ``"<player> plays
    <action>"`` line -- this function has no game-specific rendering
    knowledge of its own (ADR-0001, ADR-0006): a game with no entry in
    ``RENDERER_REGISTRY`` simply gets no extra rendering, never a crash.

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

    on_turn, on_illegal_action = _make_turn_hooks(
        match, json_mode=json_mode, renderer=renderer, print_fn=print_fn
    )
    match.run_to_completion(on_turn=on_turn, on_illegal_action=on_illegal_action)
    _print_result(match, json_mode=json_mode, print_fn=print_fn)
    return 0


_PENDING_MOVE_GRACE_SECONDS = 0.2
"""How long ``PendingMoveChannel.wait_for_pending`` blocks before giving up
and letting a stdin line be treated as chat -- see that method's docstring
for the race it closes. Long enough to comfortably cover ordinary
thread-scheduling delay between one seat's turn ending and the human's next
``decide()`` call publishing a new pending request; short enough that a
line genuinely meant as chat (sent while the opponent's own turn is going to
take much longer than this, e.g. an in-flight LLM call) is never
noticeably delayed."""


class PendingMoveChannel[ObservationT, ActionT]:
    """Thread-safe hand-off point (ADR-0009) between a chat-enabled human
    seat's ``decide()`` call -- running on ``LiveMatch``'s background match
    thread -- and the CLI's one and only stdin-reading loop, running on the
    main thread. Lets that single loop multiplex between "fulfill the
    currently-pending move" and "send a chat message" without a second
    thread ever calling ``input()``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending_legal_actions: list[ActionT] | None = None
        self._pending_changed = threading.Event()
        self._result: queue.Queue[SeatDecision[ActionT]] = queue.Queue(maxsize=1)

    def request_move(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> SeatDecision[ActionT]:
        """Called from the background match thread (via
        ``ChattableHumanController.decide``): publish that a move is now
        needed, then block until the main thread supplies one via
        ``fulfill``."""
        with self._lock:
            self._pending_legal_actions = legal_actions
            self._pending_changed.set()
        decision = self._result.get()
        with self._lock:
            self._pending_legal_actions = None
            self._pending_changed.clear()
        return decision

    def pending_legal_actions(self) -> list[ActionT] | None:
        """Called from the main thread: is a move currently being waited on
        and, if so, which actions would satisfy it? ``None`` if no
        ``request_move`` call is currently blocked."""
        with self._lock:
            return self._pending_legal_actions

    def wait_for_pending(self, timeout: float) -> list[ActionT] | None:
        """Called from the main thread: like ``pending_legal_actions``, but
        blocks up to ``timeout`` seconds for one to *become* pending first.

        Closes a real race: the instant after one seat's turn is submitted,
        there is a brief window -- ordinary thread-scheduling delay, not a
        bug in ``Match`` -- before the human's next ``decide()`` call
        publishes its own pending request. A stdin line arriving in exactly
        that window, checked only via ``pending_legal_actions()``, would be
        misread as chat even though it was meant as the next move -- and
        since nothing re-prompts for a swallowed move, the match would hang
        forever waiting for one that will never come. Waiting briefly here
        before concluding "truly no move is pending" closes that window
        without meaningfully delaying a line genuinely meant as chat.
        """
        if self._pending_changed.wait(timeout=timeout):
            return self.pending_legal_actions()
        return None

    def fulfill(self, action: ActionT) -> None:
        """Called from the main thread once it has matched a stdin line
        against the currently-pending ``legal_actions``."""
        self._result.put(SeatDecision(action=action, banter=None))


class ChattableHumanController[ObservationT, ActionT]:
    """A human ``SeatController`` whose move comes from an externally
    supplied ``PendingMoveChannel`` instead of calling ``input()`` itself
    (ADR-0009) -- so the CLI's stdin-reading loop
    (``run_live_match_with_chat``) is the only thing that ever reads stdin
    when chat is enabled. Carries no banter, same as the plain
    ``HumanCLIController`` it replaces in this mode.
    """

    def __init__(self, channel: PendingMoveChannel[ObservationT, ActionT]) -> None:
        self._channel = channel

    def decide(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> SeatDecision[ActionT]:
        return self._channel.request_move(observation, legal_actions)


def _match_legal_action(raw: str, legal_actions: list[Any]) -> Any | None:
    """Match a raw stdin line against ``legal_actions`` the same way
    ``HumanCLIController.decide`` does (``str(action)`` equality) -- ``None``
    if it matches none of them."""
    choices = {str(action): action for action in legal_actions}
    return choices.get(raw)


_CHAT_PREFIX = "chat:"
"""Explicit marker a stdin line must carry to be read as chat *while a move
is currently pending* -- see ``run_live_match_with_chat`` for why this is
needed only in that one case, not generally."""


def _strip_chat_prefix(raw: str) -> str | None:
    """``None`` if ``raw`` doesn't start with ``_CHAT_PREFIX``
    (case-insensitive); otherwise the text after it, stripped."""
    if not raw.lower().startswith(_CHAT_PREFIX):
        return None
    return raw[len(_CHAT_PREFIX) :].strip()


def run_live_match_with_chat(
    match: Match[Any, Any, Any],
    *,
    human_id: PlayerId,
    opponent_id: PlayerId,
    opponent_controller: Conversable,
    channel: PendingMoveChannel[Any, Any],
    json_mode: bool,
    renderer: Callable[[dict[str, Any]], str] | None,
    print_fn: Callable[..., None] = print,
    input_fn: Callable[[], str] = input,
) -> int:
    """Drive ``match`` to completion on a background thread (``LiveMatch``,
    ADR-0009) while the main thread runs one stdin-reading loop that lets
    ``human_id`` chat with ``opponent_id`` at any time -- including while
    ``opponent_id``'s own move-``decide()`` call is in flight -- not only on
    ``human_id``'s own turn. Returns ``0`` if the match reached completion,
    ``4`` if stdin ran out first (see below) -- ``cmd_play`` returns this as
    the process's exit code.

    ``match``'s seat map must already have ``human_id`` filled by a
    ``ChattableHumanController`` wired to ``channel`` (``cmd_play`` does
    this) -- this function only drives the loop, it doesn't build the seat
    map.

    **If stdin closes (``EOFError``) before the match is over:** this
    function does *not* then call ``LiveMatch.join()`` and wait for the
    match to finish on its own -- there may be no way for it ever to, if
    ``human_id`` is later asked to move again with no more input to supply.
    Instead it reports this plainly and returns ``4`` immediately;
    ``LiveMatch``'s background thread (a daemon thread) is simply abandoned,
    not joined -- the process exiting cleans it up. This is what stops an
    exhausted scripted/piped stdin (or a real human hitting Ctrl-D) from
    hanging the CLI forever waiting for a move that will never arrive.

    Each stdin line is routed by whether a move is currently pending
    (``channel.pending_legal_actions()``, backed by ``wait_for_pending``'s
    brief grace window -- see its docstring -- so a line arriving right as
    the opponent's turn ends and the human's begins is never misread as
    chat just because of thread-scheduling timing):

    - No move pending (it isn't ``human_id``'s turn) -- the whole line is
      sent as a chat message to ``opponent_id`` via ``LiveMatch.send_chat``,
      no marker needed, since there is nothing else the line could mean.
    - A move *is* pending and the line matches one of those legal actions --
      it fulfills that move, exactly as the plain ``HumanCLIController``
      would.
    - A move is pending but the line doesn't match any legal action --
      this is deliberately **not** treated as chat by default (a line like
      an already-occupied cell number is far more likely a mistaken move
      attempt than a coincidentally-numeric chat message; silently
      swallowing it as chat would also break every existing scripted-stdin
      test that relies on the original "invalid choice, try again" reprompt
      loop). Only a line explicitly prefixed with ``"chat:"`` is sent as
      chat in this case (with the prefix stripped); anything else prints the
      same ``"Invalid choice ...; enter one of [...]"`` message
      ``HumanCLIController`` always has, and re-prompts.
    """
    on_turn, on_illegal_action = _make_turn_hooks(
        match, json_mode=json_mode, renderer=renderer, print_fn=print_fn
    )
    live: LiveMatch[Any, Any, Any] = LiveMatch(
        match,
        conversable_seats={opponent_id: opponent_controller},
        on_turn=on_turn,
        on_illegal_action=on_illegal_action,
    )
    live.start()

    if not json_mode:
        print_fn(
            f"(Type a move number for {human_id}, or anything else to chat with "
            f"{opponent_id} while it's not your turn. On your own turn, prefix a "
            f"message with 'chat:' to talk instead of moving.)"
        )
        print_fn()

    stdin_exhausted = False
    while live.is_alive():
        try:
            raw = input_fn().strip()
        except EOFError:
            stdin_exhausted = True
            break
        if not raw:
            continue

        # A quick, non-blocking check first (the overwhelmingly common
        # case); only fall back to the short blocking wait -- closing the
        # race documented on `wait_for_pending` -- when nothing is pending
        # yet, so a move-in-progress or a genuinely-not-your-turn chat line
        # is never delayed by it.
        pending = channel.pending_legal_actions()
        if pending is None:
            pending = channel.wait_for_pending(timeout=_PENDING_MOVE_GRACE_SECONDS)
        if pending is not None:
            action = _match_legal_action(raw, pending)
            if action is not None:
                channel.fulfill(action)
                # Purely a UX smoothing delay, never a correctness
                # mechanism: gives the background thread a moment to notice
                # the match ended before this loop re-prompts, so the common
                # case of "that move won the game" doesn't need one extra,
                # pointless prompt first -- `while live.is_alive()` above is
                # what actually governs whether this loop keeps going.
                time.sleep(0.05)
                continue
            stripped = _strip_chat_prefix(raw)
            if stripped is None:
                print_fn(f"Invalid choice {raw!r}; enter one of {[str(a) for a in pending]}.")
                continue
            chat_text = stripped
        else:
            chat_text = raw

        try:
            output = live.send_chat(opponent_id, chat_text)
        except ValueError as exc:
            print_fn(str(exc))
            continue
        if not json_mode:
            print_fn(f"{opponent_id} (chat): {output.text}")

    if stdin_exhausted:
        print_fn(
            f"Input ended before the match finished (still waiting on {human_id}) "
            "-- exiting without a result."
        )
        return 4

    live.join()
    _print_result(match, json_mode=json_mode, print_fn=print_fn)
    return 0


def cmd_play(
    args: argparse.Namespace,
    *,
    print_fn: Callable[..., None] = print,
    input_fn: Callable[[], str] = input,
) -> int:
    """Handle ``agf play <game> --seat ... [--json]``.

    Parses ``--seat`` args and builds a controller per seat, constructs one
    ``Match`` over the named game's engine, and hands both to ``run_match``.
    Any ``--seat``/game-construction problem is reported and exits non-zero
    *before* the match starts -- it is a CLI-usage error, not a game-rule
    one.

    **Chat mode (ADR-0009).** If exactly one seat is ``human`` and exactly
    one *other* seat's controller implements ``Conversable`` (checked via
    ``isinstance`` -- true for a bare ``llm:openrouter/<model>`` seat, and,
    via their own pass-through ``respond()``, for one wrapped in
    ``AdvisedLLMSeatController``/``AutoplayNarratorSeatController`` too),
    that human seat's controller is swapped for a ``ChattableHumanController``
    and the match is driven by ``run_live_match_with_chat`` instead of
    ``run_match`` -- letting the human chat with that seat at any time, not
    only on their own turn. Every other combination (no human seat, two
    human seats, a human vs. a non-``Conversable`` seat like ``bot:random``,
    or more than one ``Conversable`` opponent) falls through to the
    original, non-threaded ``run_match`` path unchanged -- ``input_fn`` is
    unused there, exactly as before this ticket.

    If ``run_match``/``run_live_match_with_chat`` propagates
    ``AgentTimeoutError`` (a seat's controller failed twice in a row to
    produce a decision at all, SLICES.md V3 step 2, KAN-1285), this is
    caught here -- the same category of failure this function already
    guards against for ``SeatSpecError``/unknown-game/``ValueError`` at
    match construction -- and reported via ``print_fn`` (a JSON
    ``"agent_error"`` envelope in ``--json`` mode, matching the style of
    ``run_match``'s ``"illegal_action"``/``"result"`` envelopes; plain text
    otherwise) with a non-zero exit code, instead of letting a raw
    traceback crash the CLI mid-game.
    """
    if args.game not in GAME_REGISTRY:
        print_fn(f"Unknown game {args.game!r}; available games: {sorted(GAME_REGISTRY)}")
        return 1

    if not args.seat:
        print_fn("At least one --seat <id>=<controller-spec> is required.")
        return 2

    seats: dict[PlayerId, SeatController[Any, Any]] = {}
    order: list[PlayerId] = []
    human_ids: list[PlayerId] = []
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
        if spec == "human":
            human_ids.append(player_id)

    conversable_seats = {
        player_id: controller
        for player_id, controller in seats.items()
        if player_id not in human_ids and isinstance(controller, Conversable)
    }
    chat_enabled = len(human_ids) == 1 and len(conversable_seats) == 1

    channel: PendingMoveChannel[Any, Any] | None = None
    if chat_enabled:
        (human_id,) = human_ids
        channel = PendingMoveChannel()
        seats[human_id] = ChattableHumanController(channel)

    engine = GAME_REGISTRY[args.game]()
    try:
        match: Match[Any, Any, Any] = Match(engine, players=order, seats=seats)
    except ValueError as exc:
        print_fn(f"Cannot start {args.game!r} with seats {order!r}: {exc}")
        return 2

    renderer_factory = RENDERER_REGISTRY.get(args.game)
    renderer = renderer_factory() if renderer_factory is not None else None
    if renderer is not None and not args.json:
        # Show the starting board before the first move -- for a game with
        # no hidden information (true of tic-tac-toe today), any player's
        # observation renders the same board; a future hidden-information
        # game would need its own renderer to account for that itself.
        print_fn(renderer(match.observation_for(order[0])))
        print_fn()

    try:
        if chat_enabled and channel is not None:
            (human_id,) = human_ids
            (opponent_id, opponent_controller) = next(iter(conversable_seats.items()))
            return run_live_match_with_chat(
                match,
                human_id=human_id,
                opponent_id=opponent_id,
                opponent_controller=opponent_controller,
                channel=channel,
                json_mode=args.json,
                renderer=renderer,
                print_fn=print_fn,
                input_fn=input_fn,
            )
        return run_match(match, json_mode=args.json, renderer=renderer, print_fn=print_fn)
    except AgentTimeoutError as exc:
        if args.json:
            print_fn(json.dumps({"type": "agent_error", "error": str(exc)}))
        else:
            print_fn(f"Agent seat failed to respond: {exc}")
        return 3


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
            "llm:openrouter/openai/gpt-4o-mini; needs OPENROUTER_API_KEY set). "
            "A spec may also carry an ':advised-by='/':narrated-by=' modifier to "
            "compose it with an 'algo:<name>' algorithm, e.g. "
            "'X=llm:openrouter/openai/gpt-4o-mini:advised-by=algo:tictactoe-minimax' "
            "(an AdvisedLLMSeatController: the LLM decides, informed by the "
            "algorithm's recommendation) or "
            "'O=algo:tictactoe-minimax:narrated-by=llm:openrouter/openai/gpt-4o-mini' "
            "(an AutoplayNarratorSeatController: the algorithm decides, the LLM only "
            "narrates)."
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
