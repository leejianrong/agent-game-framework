"""Stdio MCP connector (ADR-0006, PLAN.md Shape S6, KAN-1281): exposes
``get_observation``/``list_legal_actions``/``submit_action``/
``get_state_dump`` as MCP tools over one ``Match`` instance -- see
``agent_game_framework.connectors.mcp.server`` for the implementation.
"""

from __future__ import annotations

from agent_game_framework.connectors.mcp.server import build_server, main

__all__ = ["build_server", "main"]
