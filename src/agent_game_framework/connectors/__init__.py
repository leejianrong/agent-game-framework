"""Connector packages (ADR-0006): thin translation layers over one ``Match``.

``connectors/cli`` today is the flat ``agent_game_framework.cli`` module
(KAN-1279/1280) -- moving it under this package is an out-of-scope cleanup,
not part of any ticket that has landed yet. ``connectors/mcp`` (KAN-1281) is
the first connector actually shaped as a submodule here.
"""

from __future__ import annotations
