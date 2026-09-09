"""``LiveMatch``: runs a ``Match``'s turn loop on a background thread while
exposing a thread-safe way to converse with any ``Conversable`` seat at any
time -- including while that background thread is itself blocked inside a
seat's own ``decide()`` call (ADR-0008, ADR-0009).

See ADR-0009 for the full design rationale (why this lives in ``core/``
rather than a connector, why it's a separate class rather than a change to
``Match`` itself, and the one accepted tradeoff: chatting with a seat at the
exact moment its own ``decide()`` call is in flight produces two independent,
concurrent HTTP calls to that seat's backend).

``Match``'s single-writer invariant (ADR-0003) is untouched: only the one
background thread this class starts ever calls ``submit_action`` (via
``Match.run_to_completion``); ``send_chat`` never reads or writes match
state, only this class's own per-seat conversation history.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from agent_game_framework.core.conversable import (
    Conversable,
    ConversationOutput,
    ConversationTurn,
    TextTurn,
)
from agent_game_framework.core.engine import IllegalActionError, PlayerId
from agent_game_framework.core.match import Match
from agent_game_framework.core.seat_controller import SeatDecision


class LiveMatch[StateT, ActionT, ObservationT]:
    """Drives an already-seated ``Match`` to completion on a background
    thread, while ``send_chat`` lets any other thread converse with a named
    ``Conversable`` seat at any point during that run.

    Construct with the ``match`` to drive and ``conversable_seats``, a
    ``dict[PlayerId, Conversable]`` naming which seats support chat (every
    other seat in ``match`` simply can't be chatted with via this class --
    ``send_chat`` raises ``ValueError`` for any player not in this mapping).
    The ``on_turn``/``on_illegal_action``/``on_agent_error`` hooks are passed
    straight through to ``Match.run_to_completion`` unchanged -- this class
    adds no rendering/presentation behavior of its own (ADR-0006's "thin
    adapter" framing applies here too: this is turn-loop *scheduling*, not
    presentation).
    """

    def __init__(
        self,
        match: Match[StateT, ActionT, ObservationT],
        conversable_seats: dict[PlayerId, Conversable],
        *,
        on_turn: Callable[[PlayerId, SeatDecision[ActionT]], None] | None = None,
        on_illegal_action: (
            Callable[[PlayerId, SeatDecision[ActionT], IllegalActionError], None] | None
        ) = None,
        on_agent_error: Callable[[PlayerId, Exception], None] | None = None,
    ) -> None:
        self._match = match
        self._conversable_seats = conversable_seats
        self._on_turn = on_turn
        self._on_illegal_action = on_illegal_action
        self._on_agent_error = on_agent_error
        self._history: dict[PlayerId, list[ConversationTurn]] = {
            player: [] for player in conversable_seats
        }
        self._locks: dict[PlayerId, threading.Lock] = {
            player: threading.Lock() for player in conversable_seats
        }
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._exception: BaseException | None = None

    def start(self) -> None:
        """Start driving ``match`` to completion on the background thread.
        Returns immediately -- call ``join()`` to wait for it to finish."""
        self._thread.start()

    def _run(self) -> None:
        try:
            self._match.run_to_completion(
                on_turn=self._on_turn,
                on_illegal_action=self._on_illegal_action,
                on_agent_error=self._on_agent_error,
            )
        except BaseException as exc:  # noqa: BLE001 -- re-raised verbatim by join()
            self._exception = exc

    def join(self) -> None:
        """Block until the match finishes, then re-raise whatever exception
        ``Match.run_to_completion`` raised on the background thread (e.g.
        ``AgentTimeoutError``), if any -- so a caller's exception handling is
        exactly what it would be driving ``Match`` synchronously."""
        self._thread.join()
        if self._exception is not None:
            raise self._exception

    def is_alive(self) -> bool:
        """Whether the background thread is still running the match."""
        return self._thread.is_alive()

    def send_chat(self, to_player: PlayerId, text: str) -> ConversationOutput:
        """Send one chat message to ``to_player``'s ``Conversable`` seat and
        return its reply, appending both sides of the exchange to that
        seat's conversation history.

        Thread-safe and callable at any point during the match, including
        while ``to_player``'s own ``decide()`` call is in flight on the
        background thread (see ADR-0009 for the accepted tradeoff that
        implies: the two calls proceed as independent, concurrent requests).
        Two concurrent ``send_chat`` calls to the *same* seat serialize
        (via a per-seat lock) rather than interleave that seat's history;
        calls to different seats never block each other.

        Raises ``ValueError`` if ``to_player`` has no ``Conversable``
        registered (it was never in ``conversable_seats``).
        """
        conversable = self._conversable_seats.get(to_player)
        if conversable is None:
            raise ValueError(
                f"{to_player!r} has no Conversable seat registered for chat "
                f"(known chattable seats: {sorted(self._conversable_seats)})"
            )
        incoming = TextTurn(text=text)
        with self._locks[to_player]:
            history = list(self._history[to_player])
            output = conversable.respond(history, incoming)
            self._history[to_player].append(ConversationTurn(role="human", content=incoming))
            self._history[to_player].append(ConversationTurn(role="agent", content=output))
        return output
