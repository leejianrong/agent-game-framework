"""``HumanCLIController``: a human player as a ``SeatController`` (ADR-0005,
KAN-1278).

Per ADR-0005, a human player is "just another `SeatController`
implementation" -- it prints the observation/legal actions, prompts on
stdin, and returns the parsed move with no banter. It re-prompts on
unparseable or illegal stdin input rather than passing garbage through to
``Match``, but the value it ultimately returns is always one of the
``legal_actions`` it was given -- ``Match``/``GameEngine.apply_action`` is
still the single, uniform enforcement point (see
``agent_game_framework.core.engine.IllegalActionError``); this controller
never bypasses that, it just avoids burning a ``Match.submit_action`` call
on an input a human obviously fat-fingered.

Rendering here is deliberately generic (``print(observation)``-shaped, not a
game-specific board renderer) -- a nicer, game-aware CLI rendering is
connector territory for a later card (KAN-1279), not this controller's job.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_game_framework.core.seat_controller import SeatDecision


class HumanCLIController[ObservationT, ActionT]:
    """A human player: prints the observation/legal actions, prompts on
    stdin, and returns the parsed move (``SeatController``, ADR-0005).

    ``input_fn``/``print_fn`` default to the builtins ``input``/``print`` but
    can be swapped for scripted callables in tests, so ``decide()`` is
    testable without a real interactive terminal.
    """

    def __init__(
        self,
        input_fn: Callable[[], str] = input,
        print_fn: Callable[..., None] = print,
    ) -> None:
        self._input_fn = input_fn
        self._print_fn = print_fn

    def decide(
        self, observation: ObservationT, legal_actions: list[ActionT]
    ) -> SeatDecision[ActionT]:
        """Prompt on stdin until the player enters one of ``legal_actions``.

        Matches the raw input string against ``str(action)`` for each
        candidate in ``legal_actions`` -- a simple, ``ActionT``-agnostic
        strategy that works whether actions are ``int``, ``str``, or similar
        simple JSON-safe values, without hardcoding a specific action type.
        Re-prompts, printing a short error, on unparseable input or input
        that matches no legal action.
        """
        self._print_fn("Observation:", observation)
        self._print_fn("Legal actions:", legal_actions)

        choices = {str(action): action for action in legal_actions}
        while True:
            self._print_fn("Your move: ", end="")
            raw = self._input_fn().strip()
            if raw in choices:
                return SeatDecision(action=choices[raw], banter=None)
            self._print_fn(f"Invalid choice {raw!r}; enter one of {list(choices)}.")
