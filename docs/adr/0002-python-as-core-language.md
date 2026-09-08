# ADR-0002: Core framework is written in Python

- Status: Accepted
- Date: 2026-09-08
- Deciders: Jian

## Context

The framework's third moving part (per the user's own goals) is a pre-built
algorithm/AI player per game — Catan heuristics, poker equity/solver logic,
MCTS-style search. Almost all existing research code, libraries, and prior art
for this (poker hand evaluators, board-game AI, RL/MCTS tooling) is Python-first.
That ecosystem is the single most expensive-to-rebuild dependency in this whole
project, which makes it the deciding factor over general language preference.

TypeScript was the alternative, mainly on the strength of its MCP SDK and its
fit for a future real-time web/voice front-end. Neither of those wins outweighs
losing the Python AI ecosystem, and neither is foreclosed by choosing Python now.

## Decision

The core framework, all connectors (CLI, MCP), and the agent harness are
implemented in Python (3.11+). Game-specific advisor algorithms are also
expected to be Python, to reuse existing libraries directly rather than through
a subprocess/FFI boundary.

A future real-time voice or web front-end is not required to be Python — it can
be TypeScript (or anything else) and talk to this core over the MCP connector or
a future HTTP/WebSocket transport. Language choice here does not lock in the
language of everything downstream.

## Alternatives considered

| Option | Why not |
|--------|---------|
| TypeScript throughout | Would need to reimplement or shell out to Python for poker/Catan algorithm work anyway, adding a process boundary for no benefit at this stage. |
| Python core + TypeScript front-end from day one | Real-time/voice UI is explicitly out of scope this milestone (see PLAN.md §Scope); building it now is premature. |

## Consequences

Full access to the Python game-AI/ML ecosystem for advisor algorithms, and a
simple, scriptable CLI/testing story (pytest, subprocess-driven e2e tests).
The cost: if a low-latency real-time voice pipeline is built directly on top of
this core later (rather than as a separate front-end talking over a connector),
Python's concurrency/latency characteristics may become a constraint — deferred
risk, revisit if/when the voice slice is actually planned.
