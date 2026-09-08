# ADR-0003: Core game contract — one Protocol, N players, single-writer orchestration

- Status: Accepted
- Date: 2026-09-08
- Deciders: Jian (assumed default)

## Context

Every future game (Tic-Tac-Toe now; Catan, Poker, Wavelength later) needs to
plug into the same connectors (CLI, MCP) and the same agent harness without
those layers knowing game-specific rules. That requires one minimal contract
every game implements, and that contract has to be right early: Poker has
simultaneous betting and hidden hole cards, Catan has variable player count and
a non-trivial board state, Wavelength has team-based simultaneous guessing.
Retrofitting "more than one player can be waiting to act" or "player count
varies" into a contract built 2-player/strict-turn-order would touch every game
built against it.

## Decision

A single typed Protocol (`GameEngine[StateT, ActionT, ObservationT]`) that every
game implements:

- `initial_state(players: list[PlayerId], config: dict) -> StateT`
- `current_players(state) -> list[PlayerId]` — whose turn(s) it is right now;
  more than one entry means a simultaneous-move phase (e.g. Wavelength guesses),
  not an error.
- `legal_actions(state, player) -> list[ActionT]`
- `apply_action(state, player, action) -> StateT` — raises `IllegalActionError`
  on a rule violation; the caller's state reference is left untouched, the
  orchestrator never applies a partial/invalid transition.
- `is_terminal(state) -> bool` / `winners(state) -> list[PlayerId]`
- `observation_for(state, player) -> ObservationT` — the per-player view, so
  hidden information (hole cards, hidden dev cards, the Wavelength target) is
  enforced once, in the game's own code, not reimplemented per connector.
- `serialize(state) -> dict` / `deserialize(data: dict) -> StateT` — JSON-safe,
  and `data` always carries a `schema_version` key.

A `Match` orchestrator owns the single mutable `StateT` for a running game and
is the only thing allowed to call `apply_action`; CLI and MCP both drive a game
through one `Match` instance, never by mutating state directly. This makes the
`Match` the single writer — there's no two-actors-race-to-mutate-state scenario
to resolve, only "was this action legal against the current state," which
`apply_action` already answers.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Strict single-current-player turn order (`current_player -> PlayerId \| None`) | Cheaper today, but Wavelength's simultaneous team guessing and Poker's simultaneous betting rounds don't fit it — would need a breaking contract change before the second real game. |
| Hardcode 2 players | Catan needs 3-4, Wavelength needs 2 teams of 2+; same problem as above. |
| Let each connector enforce hidden information | Duplicates the hidden-info logic in CLI and MCP separately, and a third connector added later would need it a third time. |

## Consequences

Tic-Tac-Toe (Slice 1) has to implement a contract slightly more general than it
strictly needs (a `current_players` list of size 1, always strict turn order) —
a small amount of ceremony now, paid once, so Poker/Catan/Wavelength don't each
force a contract rewrite. The cost: the Protocol can't be fully validated
against a game with real simultaneous moves or hidden information until a later
game is built against it — Slice 1 alone can't prove that part of the contract
is right, only that the plumbing exists.
