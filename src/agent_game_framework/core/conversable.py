"""``Conversable`` capability + text-conversation types (ADR-0008, ADR-0009).

Per ADR-0008, conversation is a separate, optional capability a
``SeatController`` implementation *may* additionally have -- independent of
``decide()``/``SeatDecision`` (which keep deciding moves, unchanged) and of
``GameEngine`` alike. This module carries no game-specific or connector-
specific knowledge whatsoever: it is the same three names for every game and
every connector.

Text-only for now (ADR-0008 §Decision: "``ConversationInput``/
``ConversationOutput`` are modality-tagged union types" -- only the text
variant is built this milestone; an ``AudioTurn`` counterpart slots in
alongside ``TextTurn`` later without changing this Protocol's shape).

**Why ``ConversationTurn`` carries a ``role``, not a ``PlayerId``.** ADR-0008
itself doesn't fix this field -- it only says history is "kept ... whichever
of the two [modalities] actually occurred." A ``Conversable`` implementation
(``OpenRouterBackend.respond``, ``agents/openrouter.py``) needs to rebuild a
chat-completions-style transcript (``user``/``assistant`` roles) from
``history``, which only requires knowing *which side of this one
conversation* each turn came from -- never the seat's own ``PlayerId``, which
``Conversable.respond`` is never given and has no other reason to know.
``role`` -- ``"human"`` or ``"agent"`` -- is the simplest representation that
carries exactly that, with no need to thread a seat's identity into every
``Conversable`` implementation's constructor just to label its own history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class TextTurn:
    """One text message -- either a human's chat line, or a ``Conversable``'s
    reply. The only ``ConversationInput``/``ConversationOutput`` variant
    built this milestone (ADR-0008); a future ``AudioTurn`` would be a sibling
    dataclass, not a change to this one."""

    text: str


ConversationInput = TextTurn
"""What a ``Conversable`` is asked to respond to. A type alias, not a new
name, so that adding ``AudioTurn`` later (ADR-0008) is a matter of widening
this alias to a union, not changing every ``Conversable`` implementation's
signature."""

ConversationOutput = TextTurn
"""What a ``Conversable`` responds with. See ``ConversationInput``."""


@dataclass(frozen=True)
class ConversationTurn:
    """One past turn of a conversation, as kept in ``history`` -- see the
    module docstring for why ``role`` (not a ``PlayerId``) identifies who
    said it."""

    role: Literal["human", "agent"]
    content: TextTurn


@runtime_checkable
class Conversable(Protocol):
    """A capability a ``SeatController`` implementation may additionally
    have (ADR-0008): the ability to hold a conversation, decoupled from
    deciding moves. ``@runtime_checkable`` so a caller (``cli.py``,
    ``LiveMatch``) can check ``isinstance(controller, Conversable)`` to find
    out whether a given seat supports chat at all, without every
    ``SeatController`` needing to implement it.
    """

    def respond(
        self, history: list[ConversationTurn], incoming: ConversationInput
    ) -> ConversationOutput:
        """Respond to ``incoming`` given the conversation so far.

        Called at any point relative to this seat's own move-decision
        cadence -- between turns, mid-turn, or (via ``LiveMatch``, ADR-0009)
        while this seat's own ``decide()`` call is itself in flight on
        another thread. Implementations should not assume anything about
        game state has or hasn't changed since the last call.
        """
        ...
