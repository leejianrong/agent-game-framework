"""Concrete ``SeatController`` implementations (ADR-0005, KAN-1278+): a human
player driven from stdin (``HumanCLIController``) and a uniform-random bot
(``RandomBotController``). Both live under ``src/agent_game_framework`` per
ADR-0001 -- concrete seat controllers are part of this package's agent
harness abstractions, not throwaway ``examples/`` code.
"""

from __future__ import annotations

from agent_game_framework.agents.human_cli import HumanCLIController
from agent_game_framework.agents.random_bot import RandomBotController

__all__ = [
    "HumanCLIController",
    "RandomBotController",
]
