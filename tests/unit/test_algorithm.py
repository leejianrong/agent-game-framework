"""Unit tests for the ``GameAlgorithm`` Protocol and ``AlgorithmRecommendation``
type (KAN-1288, ADR-0004): no external calls, no subprocess.

``FirstLegalActionAlgorithm`` below is a minimal, test-only ``GameAlgorithm``
that always recommends ``legal_actions[0]`` with no rationale/scores -- it
exists only to prove the Protocol's shape is usable structurally (no
explicit inheritance required); it is not a real algorithm implementation
(the Tic-Tac-Toe minimax is KAN-1289, out of scope here). This mirrors
``tests/unit/test_seat_controller.py``'s ``FirstLegalActionController``.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from agent_game_framework import algorithm as algorithm_pkg
from agent_game_framework.algorithm import AlgorithmRecommendation, GameAlgorithm


class FirstLegalActionAlgorithm:
    """Test-only ``GameAlgorithm``: always recommends ``legal_actions[0]``."""

    def recommend(
        self, observation: dict[str, object], legal_actions: list[str]
    ) -> AlgorithmRecommendation[str]:
        return AlgorithmRecommendation(best_action=legal_actions[0])


def test_algorithm_recommendation_requires_best_action_only() -> None:
    recommendation = AlgorithmRecommendation(best_action="inc")
    assert recommendation.best_action == "inc"
    assert recommendation.rationale is None
    assert recommendation.scores is None


def test_algorithm_recommendation_accepts_explicit_rationale_and_scores() -> None:
    recommendation = AlgorithmRecommendation(
        best_action="inc",
        rationale="only non-losing move",
        scores={"inc": 1.0, "dec": -1.0},
    )
    assert recommendation.best_action == "inc"
    assert recommendation.rationale == "only non-losing move"
    assert recommendation.scores == {"inc": 1.0, "dec": -1.0}


def test_algorithm_recommendation_is_frozen() -> None:
    recommendation = AlgorithmRecommendation(best_action="inc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        recommendation.best_action = "cheat"  # type: ignore[misc]


def test_fake_algorithm_satisfies_game_algorithm_protocol() -> None:
    algorithm: GameAlgorithm[dict[str, object], str] = FirstLegalActionAlgorithm()
    recommendation = algorithm.recommend(observation={}, legal_actions=["inc", "dec"])

    assert isinstance(recommendation, AlgorithmRecommendation)
    assert recommendation.best_action in ["inc", "dec"]
    assert recommendation.best_action == "inc"
    assert recommendation.rationale is None
    assert recommendation.scores is None


def _imported_module_names(source: str) -> set[str]:
    """Every module name referenced by an ``import``/``from ... import`` in
    ``source``, via straightforward AST inspection (no static-analysis
    framework needed for one module's import list)."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_algorithm_package_has_zero_dependency_on_core_or_agents() -> None:
    """Static, ADR-0004-mandated check: the ``algorithm`` package (this new
    module and whatever backs it) must never import from
    ``agent_game_framework.core`` or ``agent_game_framework.agents`` -- that
    is the literal meaning of "zero dependency on GameEngine or any specific
    game" this ticket's docstrings describe. No import-hygiene test pattern
    exists elsewhere in this repo to follow (checked ADR-0001 and the rest of
    ``tests/unit``), so this is a plain AST walk rather than a new
    static-analysis framework.
    """
    modules = [algorithm_pkg, inspect.getmodule(GameAlgorithm)]
    for module in modules:
        assert module is not None
        source = inspect.getsource(module)
        imported = _imported_module_names(source)
        for forbidden_prefix in ("agent_game_framework.core", "agent_game_framework.agents"):
            offending = {
                name
                for name in imported
                if name == forbidden_prefix or name.startswith(forbidden_prefix + ".")
            }
            assert not offending, (
                f"{module.__name__} must not import from {forbidden_prefix} (ADR-0004); "
                f"found: {offending}"
            )
