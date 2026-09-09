"""Unit tests for the ``agf`` CLI's own parsing/rendering helpers (KAN-1279,
ADR-0006): no external calls, no subprocess -- these are plain functions
tested directly, cheaply, and in isolation from argparse/``Match``/stdin.
"""

from __future__ import annotations

import pytest

from agent_game_framework.agents import HumanCLIController, OpenRouterBackend, RandomBotController
from agent_game_framework.algorithm import AdvisedLLMSeatController, AutoplayNarratorSeatController
from agent_game_framework.cli import (
    ALGORITHM_REGISTRY,
    GAME_REGISTRY,
    RENDERER_REGISTRY,
    SeatSpecError,
    build_algorithm,
    build_controller,
    parse_seat_arg,
)


def test_game_registry_has_exactly_tictactoe() -> None:
    """Only Tic-Tac-Toe is registered for now (this ticket's scope) -- but
    the registry is a dict, not a hardcoded if/else, so adding a second game
    later is a one-line addition here."""
    assert set(GAME_REGISTRY) == {"tictactoe"}


class TestParseSeatArg:
    def test_splits_id_and_controller_spec(self) -> None:
        assert parse_seat_arg("X=human") == ("X", "human")
        assert parse_seat_arg("O=bot:random") == ("O", "bot:random")

    def test_id_and_spec_may_contain_no_further_structure_assumptions(self) -> None:
        # id itself is an arbitrary PlayerId string; only the *first* '=' splits.
        assert parse_seat_arg("player-1=bot:random") == ("player-1", "bot:random")

    @pytest.mark.parametrize("raw", ["human", "Xhuman", ""])
    def test_missing_equals_sign_raises(self, raw: str) -> None:
        with pytest.raises(SeatSpecError):
            parse_seat_arg(raw)

    def test_missing_id_before_equals_raises(self) -> None:
        with pytest.raises(SeatSpecError):
            parse_seat_arg("=human")

    def test_missing_spec_after_equals_raises(self) -> None:
        with pytest.raises(SeatSpecError):
            parse_seat_arg("X=")


class TestBuildController:
    def test_human_spec_builds_human_cli_controller(self) -> None:
        controller = build_controller("human")
        assert isinstance(controller, HumanCLIController)

    def test_bot_random_spec_builds_random_bot_controller(self) -> None:
        controller = build_controller("bot:random")
        assert isinstance(controller, RandomBotController)

    @pytest.mark.parametrize("spec", ["bot", "bot:minimax", "HUMAN", ""])
    def test_unknown_spec_raises(self, spec: str) -> None:
        with pytest.raises(SeatSpecError):
            build_controller(spec)

    def test_llm_openrouter_spec_builds_openrouter_backend_with_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Model slugs themselves often contain a further '/' (OpenRouter's
        # own naming, e.g. "openai/gpt-4o-mini") -- only the fixed
        # "llm:openrouter/" prefix is stripped, so that whole slug must
        # survive intact rather than being truncated at the first '/'.
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")

        controller = build_controller("llm:openrouter/openai/gpt-4o-mini")

        assert isinstance(controller, OpenRouterBackend)
        assert controller._model == "openai/gpt-4o-mini"

    def test_llm_openrouter_spec_with_no_model_raises(self) -> None:
        with pytest.raises(SeatSpecError):
            build_controller("llm:openrouter/")

    @pytest.mark.parametrize(
        "spec", ["llm:anthropic/claude-3.5-sonnet", "llm:codex", "llm:claude-code"]
    )
    def test_llm_spec_for_an_unsupported_provider_raises_with_a_clear_message(
        self, spec: str
    ) -> None:
        # Only "llm:openrouter/..." is wired up this ticket (KAN-1286) -- any
        # other llm: provider must fail with a message naming openrouter as
        # the only supported one, not the generic "unknown controller spec"
        # message a totally unrecognized spec gets.
        with pytest.raises(SeatSpecError, match="openrouter"):
            build_controller(spec)

    def test_llm_openrouter_spec_with_no_api_key_raises_seat_spec_error_not_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # OpenRouterBackend.__init__ raises a plain ValueError for a missing
        # key; build_controller must wrap it into SeatSpecError so
        # cmd_play's single `except SeatSpecError` catch site still sees it,
        # instead of a raw ValueError escaping and crashing the CLI.
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        with pytest.raises(SeatSpecError):
            build_controller("llm:openrouter/openai/gpt-4o-mini")

    # -- V4 modifier specs (SLICES.md V4 step 5, KAN-1291) --------------

    def test_advised_by_modifier_builds_advised_llm_seat_controller(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from examples.tictactoe.algorithm import TicTacToeMinimaxAlgorithm

        # No HTTP mocking needed -- constructing OpenRouterBackend alone
        # makes no network call, exactly like the plain llm:openrouter/...
        # test above.
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")

        controller = build_controller(
            "llm:openrouter/openai/gpt-4o-mini:advised-by=algo:tictactoe-minimax"
        )

        assert isinstance(controller, AdvisedLLMSeatController)
        assert isinstance(controller._llm, OpenRouterBackend)
        assert controller._llm._model == "openai/gpt-4o-mini"
        assert isinstance(controller._algorithm, TicTacToeMinimaxAlgorithm)

    def test_narrated_by_modifier_builds_autoplay_narrator_seat_controller(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from examples.tictactoe.algorithm import TicTacToeMinimaxAlgorithm

        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")

        controller = build_controller(
            "algo:tictactoe-minimax:narrated-by=llm:openrouter/openai/gpt-4o-mini"
        )

        assert isinstance(controller, AutoplayNarratorSeatController)
        assert isinstance(controller._algorithm, TicTacToeMinimaxAlgorithm)
        assert isinstance(controller._narrator_llm, OpenRouterBackend)
        assert controller._narrator_llm._model == "openai/gpt-4o-mini"

    def test_plain_llm_spec_without_a_modifier_is_unaffected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Confirms the modifier-detection code added on top of the existing
        # llm:openrouter/... branch does not change its behavior at all when
        # no ':advised-by='/':narrated-by=' substring is present.
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")

        controller = build_controller("llm:openrouter/openai/gpt-4o-mini")

        assert isinstance(controller, OpenRouterBackend)
        assert controller._model == "openai/gpt-4o-mini"

    def test_advised_by_with_unknown_algorithm_name_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")

        with pytest.raises(SeatSpecError):
            build_controller("llm:openrouter/openai/gpt-4o-mini:advised-by=algo:no-such-algo")

    def test_advised_by_with_missing_algo_prefix_in_modifier_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")

        with pytest.raises(SeatSpecError):
            build_controller("llm:openrouter/openai/gpt-4o-mini:advised-by=tictactoe-minimax")

    def test_advised_by_with_no_algo_spec_at_all_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")

        with pytest.raises(SeatSpecError):
            build_controller("llm:openrouter/openai/gpt-4o-mini:advised-by=")

    def test_advised_by_with_no_base_spec_raises(self) -> None:
        with pytest.raises(SeatSpecError):
            build_controller(":advised-by=algo:tictactoe-minimax")

    def test_narrated_by_with_bad_nested_llm_spec_raises(self) -> None:
        with pytest.raises(SeatSpecError):
            build_controller("algo:tictactoe-minimax:narrated-by=llm:anthropic/claude-3.5-sonnet")

    def test_narrated_by_with_missing_algo_prefix_in_base_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")

        with pytest.raises(SeatSpecError):
            build_controller("tictactoe-minimax:narrated-by=llm:openrouter/openai/gpt-4o-mini")


class TestBuildAlgorithm:
    def test_known_algo_spec_builds_tictactoe_minimax_algorithm(self) -> None:
        from examples.tictactoe.algorithm import TicTacToeMinimaxAlgorithm

        algorithm = build_algorithm("algo:tictactoe-minimax")

        assert isinstance(algorithm, TicTacToeMinimaxAlgorithm)

    def test_algorithm_registry_has_exactly_tictactoe_minimax(self) -> None:
        assert set(ALGORITHM_REGISTRY) == {"tictactoe-minimax"}

    def test_unknown_algorithm_name_raises(self) -> None:
        with pytest.raises(SeatSpecError):
            build_algorithm("algo:no-such-algo")

    @pytest.mark.parametrize("spec", ["tictactoe-minimax", "", "bot:random"])
    def test_missing_algo_prefix_raises(self, spec: str) -> None:
        with pytest.raises(SeatSpecError):
            build_algorithm(spec)


def test_renderer_registry_has_exactly_tictactoe() -> None:
    """Mirrors ``GAME_REGISTRY``/``ALGORITHM_REGISTRY``'s own such test --
    a renderer is optional per game (see ``RENDERER_REGISTRY``'s docstring),
    so this dict, not a hardcoded per-game branch, is what a second game
    would extend."""
    assert set(RENDERER_REGISTRY) == {"tictactoe"}
