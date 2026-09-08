# ADR-0007: Tic-Tac-Toe is the throwaway reference game for validating the contract

- Status: Accepted
- Date: 2026-09-08
- Deciders: Jian

## Context

The framework's core contract (ADR-0003) needs to be exercised end-to-end —
engine, CLI, MCP, agent harness, advisor hook — before any real target game
(Catan, Poker, Wavelength) is built against it, per the user's own stated goal
of building the framework first. The choice was between a deliberately
throwaway toy game and using a simplified version of one of the real target
games (Wavelength was the candidate, being the mechanically simplest of the
three) to get real progress out of the validation work.

The user chose the throwaway toy game explicitly, preferring Tic-Tac-Toe.

## Decision

Tic-Tac-Toe is implemented inside this repo (`examples/tictactoe/`, see
ADR-0001) purely to validate the framework's contract and connectors. It is not
a product, is not expected to survive as anything other than a reference/test
fixture, and is deliberately kept out of the `agent-games/` sibling-repo
namespace reserved for real games.

Its 3x3 board is small enough to solve exactly with plain minimax, which is
useful independently of the "toy game" choice: it gives Slice 4's advisor-hook
demo (ADR-0004) a genuinely correct advisor for free, with no heuristic
tuning required.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Simplified Wavelength as the reference game | Rejected by the user — would have produced real progress toward a target game, but the user preferred keeping the validation work fully separate from real game builds. |
| Rock-Paper-Scissors | Simpler than Tic-Tac-Toe, but has no real turn sequencing or board state to speak of — wouldn't exercise `current_players`/state-transition plumbing as meaningfully. |

## Consequences

The contract gets validated on genuinely simple, well-understood rules with
no domain ambiguity to resolve along the way, keeping Slices 1-4 focused on the
framework's plumbing rather than on game design. The cost: none of this
example's code or tests carry forward into Catan/Poker/Wavelength — it's
throwaway effort by design, and the first real signal on whether the contract
actually fits a game with hidden information or simultaneous moves only comes
once a real game (most likely Wavelength, per its earlier evaluation as the
simplest) is built against it, in a future milestone.
