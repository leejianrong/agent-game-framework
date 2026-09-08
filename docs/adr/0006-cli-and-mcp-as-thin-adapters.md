# ADR-0006: CLI and MCP are thin adapters over one core engine API, CLI first

- Status: Accepted
- Date: 2026-09-08
- Deciders: Jian (assumed default)

## Context

The user wants both a CLI and an MCP connector ("connectors like MCP or CLI").
Both need to expose the same underlying game — a human playing via CLI and an
agent playing via MCP must be interacting with rule-identical, state-consistent
games, or bugs in one connector's game logic won't show up in the other's.

## Decision

One core `Match` orchestrator (ADR-0003) implements all game-driving logic.
The CLI and MCP connector are both thin translation layers over the exact same
`Match` API — reading input/tool-calls, calling `Match` methods, formatting
output — and contain no game rules of their own.

Build order: CLI first (fastest to write and test — a human or a scripted
stdin driver can exercise a full game without any MCP client), then MCP,
wrapping the same `Match` API with tools such as `get_observation`,
`list_legal_actions`, `submit_action`, and `get_state_dump`. MCP uses stdio
transport (matches local agent harnesses like Claude Code; no auth/networking
concerns to solve for this milestone).

The CLI supports a `--json` flag on state-dump commands so it, too, is
scriptable/diffable, not just human-readable.

## Alternatives considered

| Option | Why not |
|--------|---------|
| MCP first | The user's own target agents (OpenRouter-backed LLM harness, future Claude-Code/Codex backends) can be driven and tested without an MCP round-trip at all during Slice 1-3; CLI is the faster path to validating the core contract, and MCP is additive once that contract is proven. |
| Each connector re-implements rule checks for defense-in-depth | Duplicates logic that the single-writer `Match` already owns (ADR-0003), and risks the two connectors drifting on what counts as a legal move. |

## Consequences

A rule change or bugfix in the core engine is automatically correct for both
connectors; there is no per-connector-game-logic drift to keep in sync. The
cost: a connector-specific need (e.g. MCP wanting a different observation
shape than the CLI's printed board) has to be solved by shaping the adapter's
translation layer, not by branching the underlying engine — which is the
intended constraint, not a workaround.
