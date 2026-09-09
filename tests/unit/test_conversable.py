"""Unit tests for the ``Conversable`` capability's types/Protocol shape
(ADR-0008): no external calls, no subprocess.
"""

from __future__ import annotations

from agent_game_framework.core.conversable import (
    Conversable,
    ConversationTurn,
    TextTurn,
)


class _BareConversable:
    """A minimal ``Conversable`` implementation with no other behavior --
    proves the Protocol is satisfiable by any object with the right
    ``respond`` signature, not just ``OpenRouterBackend``."""

    def respond(self, history: list[ConversationTurn], incoming: TextTurn) -> TextTurn:
        return TextTurn(text=f"echo: {incoming.text}")


def test_a_plain_object_with_respond_satisfies_conversable_structurally() -> None:
    assert isinstance(_BareConversable(), Conversable)


def test_an_object_with_no_respond_does_not_satisfy_conversable() -> None:
    class _NotConversable:
        pass

    assert not isinstance(_NotConversable(), Conversable)


def test_text_turn_and_conversation_turn_are_plain_immutable_data() -> None:
    turn = ConversationTurn(role="human", content=TextTurn(text="hello"))
    assert turn.role == "human"
    assert turn.content.text == "hello"
