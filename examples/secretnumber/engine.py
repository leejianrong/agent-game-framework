"""``SecretNumberEngine``: a tiny hidden-information, free-text-move reference
game (ADR-0010, ADR-0011).

Exists to exercise the two parts of the ``GameEngine`` contract Tic-Tac-Toe
cannot: a **hidden** value that only one seat may see, and a **free-text**
action. ``players[0]`` (the "holder") sees a secret digit 0-9 and gives one
free-text hint; ``players[1]`` (the "guesser") then guesses the digit and
wins if right. It is deliberately Wavelength-shaped (a clue, then a guess)
without being Wavelength -- a throwaway like ``examples/tictactoe``.

Like ``TicTacToeEngine`` it never mutates a state it is handed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from agent_game_framework.core import FreeText, IllegalActionError, PlayerId

SECRETNUMBER_SCHEMA_VERSION = 1
MAX_HINT_WORDS = 5

Action = int | str


@dataclass
class SecretNumberState:
    """``players`` is ``[holder, guesser]``. ``hint`` is ``None`` until the
    holder has given one; ``guess`` is ``None`` until the guesser has."""

    players: list[PlayerId]
    secret: int
    hint: str | None = None
    guess: int | None = None


class SecretNumberEngine:
    def initial_state(self, players: list[PlayerId], config: dict[str, Any]) -> SecretNumberState:
        if len(players) != 2:
            raise ValueError(f"secretnumber requires exactly 2 players, got {players!r}")
        secret = config.get("secret")
        if secret is None:
            secret = random.Random(config.get("seed")).randrange(10)
        if not (isinstance(secret, int) and 0 <= secret <= 9):
            raise ValueError(f"secret must be an int 0-9, got {secret!r}")
        return SecretNumberState(players=list(players), secret=secret)

    def current_players(self, state: SecretNumberState) -> list[PlayerId]:
        if self.is_terminal(state):
            return []
        return [state.players[0] if state.hint is None else state.players[1]]

    def legal_actions(self, state: SecretNumberState, player: PlayerId) -> list[Any]:
        if player not in self.current_players(state):
            return []
        if state.hint is None:
            return [FreeText(max_words=MAX_HINT_WORDS)]
        return list(range(10))

    def apply_action(
        self, state: SecretNumberState, player: PlayerId, action: Action
    ) -> SecretNumberState:
        if player not in self.current_players(state):
            raise IllegalActionError(f"{player!r} may not act now; it is not their turn")
        if state.hint is None:
            if not isinstance(action, str) or not action.strip():
                raise IllegalActionError("the hint must be non-empty text")
            hint = action.strip()
            if "\n" in hint or len(hint.split()) > MAX_HINT_WORDS:
                raise IllegalActionError(
                    f"the hint must be one line of at most {MAX_HINT_WORDS} words"
                )
            if str(state.secret) in hint:
                raise IllegalActionError("the hint must not contain the secret digit")
            return SecretNumberState(state.players, state.secret, hint=hint)
        if isinstance(action, bool) or not isinstance(action, int) or not 0 <= action <= 9:
            raise IllegalActionError(f"a guess must be an int 0-9, got {action!r}")
        return SecretNumberState(state.players, state.secret, state.hint, action)

    def is_terminal(self, state: SecretNumberState) -> bool:
        return state.guess is not None

    def winners(self, state: SecretNumberState) -> list[PlayerId]:
        return list(state.players) if state.guess == state.secret else []

    def observation_for(self, state: SecretNumberState, player: PlayerId) -> dict[str, Any]:
        """Only the holder sees ``secret``; the guesser sees the hint, and the
        secret too once the game is over."""
        obs: dict[str, Any] = {
            "you": player,
            "role": "holder" if player == state.players[0] else "guesser",
            "hint": state.hint,
            "current_players": self.current_players(state),
        }
        if player == state.players[0] or self.is_terminal(state):
            obs["secret"] = state.secret
        return obs

    def serialize(self, state: SecretNumberState) -> dict[str, Any]:
        return {
            "schema_version": SECRETNUMBER_SCHEMA_VERSION,
            "players": list(state.players),
            "secret": state.secret,
            "hint": state.hint,
            "guess": state.guess,
        }

    def deserialize(self, data: dict[str, Any]) -> SecretNumberState:
        if data.get("schema_version") != SECRETNUMBER_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data.get('schema_version')!r}")
        return SecretNumberState(
            players=list(data["players"]),
            secret=data["secret"],
            hint=data["hint"],
            guess=data["guess"],
        )
