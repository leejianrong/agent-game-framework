# agent-game-framework

Installable Python framework for playing turn-based/simultaneous-move games with any mix
of human and AI-controlled seats — including zero-human, fully autonomous matches. Ships
one reference game (Tic-Tac-Toe) plus a CLI and an MCP connector so an agent harness (or a
human) can drive a match identically. See `docs/PLAN.md` and `docs/adr/` for the design.

**Status:** V1 (core engine, CLI, human/bot seats) is complete. V2 (MCP connector) is in
progress — the stdio server and bot-filled seat assignment are done; a full MCP test
harness is next.

## Install (editable, for development)

```
uv sync --all-extras --dev
```

or, from a plain venv:

```
pip install -e .
```

## Usage

Play a full game from the CLI, human vs. a random bot:

```
agf play tictactoe --seat X=human --seat O=bot:random
```

Zero human seats works identically — it's just a different seat map:

```
agf play tictactoe --seat X=bot:random --seat O=bot:random
```

Add `--json` to any `play` invocation to emit one JSON line per turn instead of a rendered
board (scriptable/diffable output).

An agent can instead drive a match over MCP (stdio transport) — one seat is controlled by
whichever MCP client calls `submit_action` for it, the other can be auto-played by a bot so
a full game completes without a second client:

```
python -m agent_game_framework.connectors.mcp.server
```

## Contributing

See `CLAUDE.md` for the day-to-day workflow (branch/PR conventions, local checks, ADR
process).

## License

Apache License 2.0 — see `LICENSE`.
