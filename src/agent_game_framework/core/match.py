"""``Match`` orchestrator: the single writer of a running game's state
(ADR-0003, PLAN.md Shape S2).

``Match`` owns the one mutable ``StateT`` for a game and is the only thing
allowed to call ``GameEngine.apply_action``. The CLI and MCP connectors
drive a game through one ``Match`` instance each, never by mutating engine
state directly -- that's what makes ``Match`` the single writer, with no
two-actors-race-to-mutate-state scenario to resolve.

As of KAN-1280, ``Match`` also optionally owns the seat -> ``SeatController``
mapping (ADR-0005, PLAN.md Shape S2: "seat -> `SeatController` mapping,
drives the turn loop by calling `current_players` then each seat's
`decide()`") and can drive the turn loop itself via ``play_turn()``/
``run_to_completion()``. This is additive: every low-level method that
existed before this ticket (``current_players``, ``legal_actions``,
``submit_action``, ``is_terminal``, ``winners``, ``observation_for``,
``serialize``/``deserialize``, the ``state`` property) is unchanged and still
useful directly -- e.g. for a future MCP connector that wants fine-grained
per-call control, or tests that don't need a full seat map. ``seats`` is
``None`` by default, so every pre-existing caller that only ever passed
``engine``/``players``/``config`` keeps working unchanged.

Zero-required-human-seats (R1) falls out of this directly: whether a given
seat's controller happens to be a human-input adapter or an all-AI one is
just a difference in *which* ``SeatController`` sits in the ``seats``
mapping -- ``play_turn()``/``run_to_completion()`` never branch on that,
so a 1-human/N-agent match and an all-AI (0-human) match are the exact same
code path with a different configuration.

As of KAN-1285 (SLICES.md V3 step 2), ``play_turn()`` also handles a
``controller.decide()`` call that itself *raises*, as opposed to returning a
well-formed-but-illegal ``SeatDecision`` (that latter case is
``IllegalActionError``'s territory -- see ``submit_action`` -- and is
unchanged by this ticket). This module deliberately catches that failure via
a broad ``except Exception``, never by importing and naming a specific
controller's exception type (e.g. ``agent_game_framework.agents.openrouter``'s
``ResponseParseError``, or an ``httpx2`` network exception): ``core`` must
never import from ``agents`` (ADR-0001's package-boundary layering -- the
core contract can't know concrete controllers exist, or every new
``SeatController`` implementation would require a ``core`` change to be
handled). This also keeps the handling controller-implementation-agnostic
per ADR-0005: a seat's failure is never treated differently because of
*which* ``SeatController`` sits behind it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_game_framework.core.engine import GameEngine, IllegalActionError, PlayerId
from agent_game_framework.core.seat_controller import (
    AgentTimeoutError,
    SeatController,
    SeatDecision,
)


class Match[StateT, ActionT, ObservationT]:
    """Drives one game's turn loop on top of a ``GameEngine`` implementation.

    Construct with the engine implementation plus the players and config for
    a new match; ``initial_state`` is called immediately. Optionally also
    pass ``seats``, a seat -> ``SeatController`` mapping, to let ``Match``
    itself drive the turn loop via ``play_turn()``/``run_to_completion()``
    (PLAN.md Shape S2) instead of a caller driving
    ``current_players()``/``submit_action()`` by hand.
    """

    def __init__(
        self,
        engine: GameEngine[StateT, ActionT, ObservationT],
        players: list[PlayerId],
        config: dict[str, Any] | None = None,
        seats: dict[PlayerId, SeatController[ObservationT, ActionT]] | None = None,
    ) -> None:
        self._engine = engine
        self._state = engine.initial_state(players, config or {})
        self._seats = seats

    @property
    def state(self) -> StateT:
        """The current engine state.

        Treat as read-only from outside ``Match``: by convention, nothing
        but ``Match.submit_action``/``Match.deserialize`` changes it.
        """
        return self._state

    def current_players(self) -> list[PlayerId]:
        """Whose turn(s) it is right now (see ``GameEngine.current_players``)."""
        return self._engine.current_players(self._state)

    def legal_actions(self, player: PlayerId) -> list[ActionT]:
        """Actions ``player`` may currently take."""
        return self._engine.legal_actions(self._state, player)

    def submit_action(self, player: PlayerId, action: ActionT) -> StateT:
        """Apply ``action`` on behalf of ``player``, and return the new state.

        Raises ``IllegalActionError`` -- and leaves ``Match``'s internal
        state completely unchanged -- if either:

        - ``player`` is not currently in ``current_players()`` (it is not
          their turn, or not a simultaneous-move phase they're part of), or
        - the engine itself rejects the action via ``apply_action``.
        """
        if player not in self._engine.current_players(self._state):
            raise IllegalActionError(
                f"{player!r} is not in current_players(); it is not their turn to act"
            )
        # Only rebind self._state after a successful apply_action call, so a
        # raised IllegalActionError never leaves Match holding a partial or
        # invalid transition (ADR-0003).
        new_state = self._engine.apply_action(self._state, player, action)
        self._state = new_state
        return self._state

    def is_terminal(self) -> bool:
        """Whether the game has ended (see ``GameEngine.is_terminal``)."""
        return self._engine.is_terminal(self._state)

    def winners(self) -> list[PlayerId]:
        """Players who won (see ``GameEngine.winners``)."""
        return self._engine.winners(self._state)

    def observation_for(self, player: PlayerId) -> ObservationT:
        """The per-player view of the current state (see ``GameEngine.observation_for``)."""
        return self._engine.observation_for(self._state, player)

    def serialize(self) -> dict[str, Any]:
        """A JSON-safe dict for the current state, via the engine's ``serialize``."""
        return self._engine.serialize(self._state)

    def deserialize(self, data: dict[str, Any]) -> None:
        """Replace the current state from ``data``, via the engine's ``deserialize``.

        ``data`` always carries a ``schema_version`` key; interpreting it is
        entirely the engine's responsibility, not ``Match``'s.
        """
        self._state = self._engine.deserialize(data)

    def play_turn(
        self,
        *,
        on_turn: Callable[[PlayerId, SeatDecision[ActionT]], None] | None = None,
        on_illegal_action: (
            Callable[[PlayerId, SeatDecision[ActionT], IllegalActionError], None] | None
        ) = None,
        on_agent_error: Callable[[PlayerId, Exception], None] | None = None,
    ) -> None:
        """Drive one round of ``current_players()`` through their seat controllers.

        Requires a seat map (``seats=`` on ``__init__``). For each player
        named by ``current_players()`` at the moment this is called (a
        snapshot taken once, not re-read mid-round): looks up that player's
        ``SeatController``, calls ``controller.decide()`` with the player's
        current ``observation_for()``/``legal_actions()``, and submits the
        resulting action via ``submit_action()``.

        Raises ``ValueError`` -- a programmer-error signal, never a
        game-rule one -- if no ``seats`` mapping was ever provided, or if a
        player named by ``current_players()`` has no entry in it.

        On a successful ``submit_action``, calls ``on_turn(player,
        decision)`` if given, then continues to the next player in this
        round.

        On ``IllegalActionError`` from ``submit_action`` -- per
        ``submit_action``'s contract, ``Match``'s state is left completely
        unchanged, so ``player`` remains in ``current_players()`` afterwards
        -- behavior depends on ``on_illegal_action``:

        - if given, it is called as ``on_illegal_action(player, decision,
          error)`` and this method continues to the next player in this
          round (mirroring the CLI's original reject-and-continue loop:
          this never silently skips the player's turn -- the caller must
          call ``play_turn()``/``run_to_completion()`` again to re-ask the
          same player, since ``current_players()`` still names them);
        - if not given, the ``IllegalActionError`` propagates to the
          caller, who may catch it and retry by calling ``play_turn()``
          again -- state is unchanged, so the same player is still up.

        This is a **different, unbounded, caller-driven** retry contract
        than the one below for a controller that raises: ``on_illegal_action``
        exists because, in normal operation, a well-behaved
        ``SeatController`` should never actually trigger it (see
        ``HumanCLIController``, which re-prompts internally until it gets a
        legal move) -- it is a defensive, uniform-across-controller-kinds
        path, not a policy this method enforces a cap on. Do not add a
        bounded-retry cap to *this* path; that would special-case AI-backed
        seats, contradicting ADR-0005's "never handled differently because
        the seat happens to be human."

        ``controller.decide()`` itself may raise (SLICES.md V3 step 2,
        KAN-1285) instead of returning -- e.g. an ``OpenRouterBackend``
        seeing an HTTP timeout, or a response it can't parse into a
        ``SeatDecision`` at all. Since nothing has been submitted yet at
        that point, ``Match``'s state is untouched either way. On such a
        failure, ``play_turn`` retries **exactly once**, immediately,
        reusing the same already-fetched ``observation``/``legal_actions``
        (state hasn't changed, so there's nothing to refetch). If given,
        ``on_agent_error(player, exc)`` is called after each failed attempt
        -- a reporting hook only, mirroring ``on_illegal_action``'s shape
        but never altering control flow: whether or not it is given, a
        second consecutive failure always raises ``AgentTimeoutError``
        (chained from that second exception via ``__cause__``) out of this
        method. Unlike the ``IllegalActionError``/``on_illegal_action`` path
        above, there is no continue-the-round option here: this is a
        brand-new failure mode with no pre-existing hook contract to
        preserve, and an unbounded retry on a controller that cannot
        produce a decision at all would hang the turn loop rather than
        merely re-ask a well-behaved controller for a different move.
        """
        if self._seats is None:
            raise ValueError(
                "Match.play_turn() requires a seat map; pass `seats=` to "
                "Match.__init__, or drive current_players()/submit_action() "
                "directly for fine-grained control without a seat map."
            )
        for player in self.current_players():
            controller = self._seats.get(player)
            if controller is None:
                raise ValueError(
                    f"no SeatController registered for player {player!r}; "
                    "check the `seats` mapping passed to Match.__init__"
                )
            observation = self.observation_for(player)
            legal_actions = self.legal_actions(player)
            decision = self._decide_with_one_retry(
                controller, player, observation, legal_actions, on_agent_error
            )

            try:
                self.submit_action(player, decision.action)
            except IllegalActionError as exc:
                if on_illegal_action is None:
                    raise
                on_illegal_action(player, decision, exc)
                continue

            if on_turn is not None:
                on_turn(player, decision)

    def _decide_with_one_retry(
        self,
        controller: SeatController[ObservationT, ActionT],
        player: PlayerId,
        observation: ObservationT,
        legal_actions: list[ActionT],
        on_agent_error: Callable[[PlayerId, Exception], None] | None,
    ) -> SeatDecision[ActionT]:
        """Call ``controller.decide()``, retrying exactly once on any
        exception, then raising ``AgentTimeoutError`` if the retry also
        fails. See ``play_turn``'s docstring for the full policy this
        implements; split out only to keep ``play_turn``'s per-player loop
        readable.

        Deliberately catches ``Exception`` broadly, never a specific
        controller's exception type -- see this module's docstring for why
        (``core`` must never import from ``agents``).
        """
        try:
            return controller.decide(observation, legal_actions)
        except Exception as first_exc:
            if on_agent_error is not None:
                on_agent_error(player, first_exc)
            try:
                return controller.decide(observation, legal_actions)
            except Exception as second_exc:
                if on_agent_error is not None:
                    on_agent_error(player, second_exc)
                raise AgentTimeoutError(
                    f"SeatController for player {player!r} failed to produce a "
                    f"decision after 1 retry: {second_exc!r}"
                ) from second_exc

    def run_to_completion(
        self,
        *,
        on_turn: Callable[[PlayerId, SeatDecision[ActionT]], None] | None = None,
        on_illegal_action: (
            Callable[[PlayerId, SeatDecision[ActionT], IllegalActionError], None] | None
        ) = None,
        on_agent_error: Callable[[PlayerId, Exception], None] | None = None,
    ) -> None:
        """Drive the match to completion, calling ``play_turn()`` repeatedly
        until ``is_terminal()``.

        A thin loop over ``play_turn()`` -- see its docstring for the full
        seat-map/hook contract, which applies identically here. Deliberately
        has no knowledge of any particular connector (no ``print``, no JSON
        formatting): a connector supplies ``on_turn``/``on_illegal_action``/
        ``on_agent_error`` to react (render a board, emit a JSON line, report
        an error) after each turn, keeping ``Match`` the sole owner of
        turn-loop mechanics (PLAN.md Shape S2) and the connector the sole
        owner of presentation (ADR-0006) -- the same hooks are reusable,
        unchanged, by a future MCP connector (KAN-1281+) that wants to drive
        this exact loop with different reactions.

        This loop itself needed no change for the bounded-retry-then-
        ``AgentTimeoutError`` behavior (KAN-1285): that policy lives entirely
        inside ``play_turn()``, so ``AgentTimeoutError`` simply propagates
        out of this ``while`` loop exactly like an uncaught
        ``IllegalActionError`` already could.
        """
        while not self.is_terminal():
            self.play_turn(
                on_turn=on_turn,
                on_illegal_action=on_illegal_action,
                on_agent_error=on_agent_error,
            )
