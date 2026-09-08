# ADR-0001: This repo is the reusable core framework; each real game is a sibling repo

- Status: Accepted
- Date: 2026-09-08
- Deciders: Jian (assumed default, not user-escalated — low ambiguity)

## Context

The stated goal is a framework reusable across Catan, Poker, and Wavelength, plus
a "repo structure I can keep reusing." The parent directory is already named
`agent-games/`, with this project living at `agent-games/agent-game-framework/` —
implying sibling folders for the actual games rather than one monorepo.

A monorepo (framework + every game in one tree) was the alternative, but it
would force every game to release/version in lockstep with the framework and with
each other, which isn't true here: Catan, Poker, and Wavelength will be built
months apart, by different amounts of work, and don't need to share a release
train.

## Decision

`agent-game-framework` is a standalone, installable Python package containing
only the core engine contract, connectors (CLI, MCP), and the agent harness
abstractions. It has no game-specific code beyond one throwaway example.

Each real target game (Catan, Poker, Wavelength) is its own sibling repo under
`agent-games/`, and depends on `agent-game-framework` (as a local/path or git
dependency during development; a private/published package later if that's ever
needed).

The one exception is the Tic-Tac-Toe reference game used to validate this
repo's contract (see ADR-0007) — it lives inside this repo under `examples/`,
since it's discarded once the contract is proven and isn't a product in its own
right.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Monorepo containing framework + all games | Forces games to share a release cadence and dependency set they don't need to share; makes "a repo structure I can keep reusing" harder since there's only one repo, not a template. |
| Framework + games all as directories with no package boundary, sharing one `src/` | Blurs the "core contract vs game implementation" line this whole project exists to establish; every game's code becomes trivially cross-couplable to every other game's. |

## Consequences

Reusing the framework across a new game means adding a dependency, not copying
files — the intended "reusable repo structure" goal is met through packaging,
not templating. The cost: this repo must have a real installable package
boundary (a `pyproject.toml`, a stable public API surface) from the start, not
something deferred to "whenever it's needed elsewhere" — Slice 1 has to produce
something actually installable by a sibling repo, not just runnable in place.
