"""Unit tests for the Secret Number reference game: the hidden-information and
free-text halves of the ``GameEngine`` contract (ADR-0010, ADR-0011)."""

from __future__ import annotations

import pytest

from agent_game_framework.core import FreeText, IllegalActionError
from examples.secretnumber import SecretNumberEngine

ENGINE = SecretNumberEngine()


def _start(secret: int = 7) -> object:
    return ENGINE.initial_state(["A", "B"], {"secret": secret})


def test_hint_phase_offers_the_free_text_marker_to_the_holder_only() -> None:
    state = _start()
    assert ENGINE.legal_actions(state, "A") == [FreeText(max_words=5)]
    assert ENGINE.legal_actions(state, "B") == []


def test_guesser_never_sees_the_secret_until_the_game_ends() -> None:
    state = ENGINE.apply_action(_start(), "A", "warm and smoky")  # type: ignore[arg-type]
    assert "secret" not in ENGINE.observation_for(state, "B")
    assert ENGINE.observation_for(state, "A")["secret"] == 7
    assert ENGINE.observation_for(state, "B")["hint"] == "warm and smoky"

    done = ENGINE.apply_action(state, "B", 3)
    assert ENGINE.observation_for(done, "B")["secret"] == 7
    assert ENGINE.winners(done) == []


def test_correct_guess_wins_for_both() -> None:
    state = ENGINE.apply_action(_start(), "A", "lucky")  # type: ignore[arg-type]
    done = ENGINE.apply_action(state, "B", 7)
    assert ENGINE.is_terminal(done)
    assert ENGINE.winners(done) == ["A", "B"]


@pytest.mark.parametrize(
    "hint", ["", "   ", "one two three four five six", "the number 7", "two\nlines"]
)
def test_bad_hints_are_rejected_and_state_is_unchanged(hint: str) -> None:
    state = _start()
    before = ENGINE.serialize(state)  # type: ignore[arg-type]
    with pytest.raises(IllegalActionError):
        ENGINE.apply_action(state, "A", hint)  # type: ignore[arg-type]
    assert ENGINE.serialize(state) == before  # type: ignore[arg-type]


def test_out_of_turn_and_bad_guess_are_rejected() -> None:
    state = _start()
    with pytest.raises(IllegalActionError):
        ENGINE.apply_action(state, "B", 3)  # type: ignore[arg-type]
    state = ENGINE.apply_action(state, "A", "hint")  # type: ignore[arg-type]
    for bad in (10, -1, True, "3"):
        with pytest.raises(IllegalActionError):
            ENGINE.apply_action(state, "B", bad)  # type: ignore[arg-type]


def test_serialize_round_trips_with_schema_version_and_seed_is_reproducible() -> None:
    state = ENGINE.apply_action(_start(), "A", "hint")  # type: ignore[arg-type]
    data = ENGINE.serialize(state)
    assert data["schema_version"] == 1
    assert ENGINE.serialize(ENGINE.deserialize(data)) == data
    a = ENGINE.initial_state(["A", "B"], {"seed": 5})
    b = ENGINE.initial_state(["A", "B"], {"seed": 5})
    assert a.secret == b.secret
