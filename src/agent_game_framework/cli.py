"""Command-line entry point for agent-game-framework (console script: ``agf``).

This is a minimal placeholder (KAN-1274, the package-skeleton card): it exists
only so ``agf --help`` works and exits 0, satisfying this repo's own
pip-installability acceptance test (see docs/SLICES.md, V1 e2e). Real
subcommands (e.g. ``agf play``) land in a later card (KAN-1279) once the core
engine (``GameEngine``, ``Match``, ``SeatController``) exists.
"""

from __future__ import annotations

import argparse

from agent_game_framework import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="agf",
        description="agent-game-framework CLI (no commands yet -- package skeleton only).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``agf`` console script."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
