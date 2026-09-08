# Agent Game Framework: Plan

Status: agreed · Milestone: MVP (framework core, before any real target game)

## Problem

Playing board/card/party games against AI today means either a game-specific
bot with a fixed, narrow interface, or an LLM improvising badly because it only
sees raw text and no game-legal structure. There's no reusable foundation for
"a game engine that both a human and one or more AI agents can play through the
same rules, with an agent able to draw on a purpose-built algorithm's strong
play in addition to the raw state — without that algorithm being welded to the
game's own code" — every game that wants this (Catan, Poker, Wavelength) would
otherwise reinvent the plumbing from scratch.

Building any of those three real games first, without settling this plumbing,
means re-deriving the same contract three times and likely getting it wrong at
least once in a way that's expensive to unwind after a game is already built on it.

## Solution

A small, installable Python framework: a core contract every turn-based/
simultaneous-move game implements once, two connectors (CLI, MCP) that drive
any such game identically, and an agent harness that can seat a human, an
LLM-backed agent, or a plain algorithmic bot into any seat — including a match
with no human at all. A game algorithm (e.g. a Catan heuristic, a poker
equity/solver) is a standalone, standardized component that is never part of a
game's own implementation — it depends only on that game's public types, so
someone else can write their own algorithm for an existing game without
touching that game's repo. Two reusable, framework-provided ways to use one:
an LLM that decides for itself but is automatically shown the algorithm's
recommendation each turn, or the algorithm deciding every move outright while
an LLM only narrates/banters about what it did.

This milestone ships no real target game. It ships the framework, proven by a
throwaway Tic-Tac-Toe example that exercises every part of the contract:
engine, both connectors, a human seat, an AI seat, an all-AI match, and both
algorithm-composition modes.

## Users and actors

- **Primary user:** Jian, playing a game via the CLI (as a human seat) against
  one or more AI-controlled seats. The framework's job is to serve this
  experience, not to be a generically "correct" abstraction for its own sake.
- **AI agent (LLM-backed):** a seat controller that receives an observation
  (its legal view of state) and legal actions, and returns a legal action plus
  optional banter text — optionally informed, internally, by a game algorithm's
  recommendation (ADR-0004).
- **Algorithmic/scripted bot:** a seat controller with no LLM involved (e.g. a
  minimax bot), used as a real opponent, as the decision-maker inside an
  advised LLM seat, or as the decision-maker an LLM narrates for.
- **Third-party algorithm author:** someone who writes their own `GameAlgorithm`
  for an existing game using only that game's published observation/action
  types — never touches the game's own repo.
- **MCP client (a coding agent, e.g. Claude Code):** consumes the same
  observation/legal-actions/submit-action surface as the LLM harness, to drive
  or spectate a match programmatically.
- When actors conflict (e.g. an AI seat's decision arrives while a human is
  mid-input on a shared terminal), the human's CLI turn wins — the framework
  never auto-advances a human's seat.

## Scope

**In this milestone.**
- A core `GameEngine` Protocol (state, legal actions, apply, terminal/winners,
  per-player observation, JSON serialize/deserialize with a schema version) —
  general enough for N players and simultaneous-move phases (ADR-0003).
- A `Match` orchestrator: the single writer of game state, seat -> controller
  mapping, turn-loop driver.
- A `SeatController` Protocol covering humans, LLM agents, and plain
  algorithmic bots uniformly — a match with 1 human + N agents and a match
  with 0 humans (all AI) are both supported as configurations of the same code
  path, not separate features (ADR-0005).
- A standalone `GameAlgorithm` Protocol + `AlgorithmRecommendation`, entirely
  decoupled from `GameEngine` and `SeatController` — a game never owns or
  exposes "its" algorithm; it's just a component someone (the game's own
  author, or a third party) implements against that game's public types
  (ADR-0004).
- Two framework-provided, reusable `SeatController` compositions:
  `AdvisedLLMSeatController` (LLM decides, informed by an auto-computed
  recommendation) and `AutoplayNarratorSeatController` (algorithm decides
  outright, LLM only narrates) (ADR-0004).
- CLI connector: assign any mix of controllers to seats, play a full game,
  `--json` state dumps (ADR-0006).
- MCP connector (stdio transport): `get_observation`, `list_legal_actions`,
  `submit_action`, `get_state_dump` tools over the same `Match` API (ADR-0006).
- `OpenRouterBackend`: the first real `SeatController` backed by an LLM,
  producing a structured action + short free-text banter (ADR-0005).
- A throwaway Tic-Tac-Toe example (`examples/tictactoe/`) implementing the
  contract, including a minimax `GameAlgorithm` (in its own sibling module,
  separate from the game logic) demonstrated in both composition modes
  (ADR-0004, ADR-0007).
- Installable packaging (`pyproject.toml`) so a sibling game repo can depend on
  this one (ADR-0001).

**Out.**
- Catan, Poker, and real Wavelength — this milestone builds and proves the
  framework only; the next real game gets its own planning pass, which is
  expected to re-open the parts of this contract that haven't been exercised
  yet (hidden information, simultaneous moves — see ADR-0003's consequences).
- Voice (TTS/STT), Runpod-hosted models, and true real-time performance. Only
  the text half of "feel human" (LLM banter as text) is in scope; voice is a
  future `SeatController` implementation, not built here (ADR-0005, Q8).
- Claude-Code/Codex-as-agent-backend — the abstraction supports it, but only
  `OpenRouterBackend` is actually built.
- Persistence/replay of matches, and networked (non-local) multiplayer (Q9, Q10).
- Any real algorithm for a real game (Catan heuristics, poker equity). Only a
  Tic-Tac-Toe minimax demo is built, to prove the plumbing (ADR-0004).
- On-demand tool-calling for algorithm consultation (the LLM explicitly
  invoking the algorithm mid-turn). Both composition modes in this milestone
  compute the recommendation automatically every turn (ADR-0004).

## Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| R0 | One core contract lets a game plug into both connectors and the agent harness without connector- or harness-specific game code | Core goal |
| R1 | A `Match` supports any mix of human and AI seats, including zero human seats | Must-have |
| R2 | A game algorithm is a standalone component (never part of a game's own implementation), usable in both an LLM-advised and an algorithm-autoplay-with-narration mode | Must-have |
| R3 | An LLM-backed seat produces a legal action plus separate free-text banter | Must-have |
| R4 | CLI and MCP connectors drive matches through identical underlying logic (no divergent rule-checking) | Must-have |
| R5 | Illegal/malformed input from any seat (human or AI) is rejected with a structured error, engine state unchanged | Must-have |
| R6 | This repo is installable as a dependency from a sibling game repo | Must-have |
| R7 | Game state is JSON-serializable with a schema version, even with no persistence yet | Nice-to-have |

## Shape

| Part | Mechanism | ADR |
|------|-----------|-----|
| S1 | `GameEngine` Protocol: `initial_state`, `current_players`, `legal_actions`, `apply_action`, `is_terminal`, `winners`, `observation_for`, `serialize`/`deserialize` | ADR-0003 |
| S2 | `Match` orchestrator: sole owner of mutable state, seat -> `SeatController` mapping, drives the turn loop by calling `current_players` then each seat's `decide()` | ADR-0003, ADR-0005 |
| S3 | `SeatController` Protocol + implementations: `HumanCLIController`, `OpenRouterBackend`, `RandomBotController` | ADR-0005 |
| S4 | `GameAlgorithm` Protocol + `AlgorithmRecommendation`, and the two composite controllers `AdvisedLLMSeatController` / `AutoplayNarratorSeatController` that consume one | ADR-0004 |
| S5 | CLI connector: seat assignment flags, turn-by-turn text rendering, `--json` state dump | ADR-0006 |
| S6 | MCP connector (stdio): `get_observation`, `list_legal_actions`, `submit_action`, `get_state_dump` tools wrapping one `Match` | ADR-0006 |
| S7 | Tic-Tac-Toe reference implementation of S1, plus a minimax `GameAlgorithm` (own sibling module) used via both S4 composite controllers | ADR-0004, ADR-0007 |

## Affordances

**CLI.**

| Affordance | Place | Wires to |
|------------|-------|----------|
| `agf play tictactoe --seat X=human --seat O=llm:openrouter/<model>` | CLI command | `Match` with a seat map of `{X: HumanCLIController, O: OpenRouterBackend}` |
| `agf play tictactoe --seat X=bot:random --seat O=bot:random` | CLI command | all-AI match, zero human controllers, same code path |
| `agf play tictactoe --seat X=llm:openrouter/<model>:advised-by=algo:tictactoe-minimax` | CLI command | `AdvisedLLMSeatController(llm=OpenRouterBackend, algorithm=<minimax>)` in that seat |
| `agf play tictactoe --seat X=algo:tictactoe-minimax:narrated-by=llm:openrouter/<model>` | CLI command | `AutoplayNarratorSeatController(algorithm=<minimax>, narrator_llm=OpenRouterBackend)` in that seat |
| `agf play ... --json` | CLI flag | `Match.dump_state()` printed as JSON instead of the rendered board |

Exact flag syntax above is illustrative, not a locked API — finalized when S5 is built.

**Non-UI.**

| Affordance | Kind | Wires to |
|------------|------|----------|
| MCP tools (`get_observation`, `list_legal_actions`, `submit_action`, `get_state_dump`) | MCP server (stdio) | Same `Match` instance a CLI-driven game would use |
| `OpenRouterBackend.decide(...)` | Library call | OpenRouter chat/tool-call API |
| `GameAlgorithm.recommend(...)` (Tic-Tac-Toe minimax) | Library call | Called automatically, every turn, by `AdvisedLLMSeatController`/`AutoplayNarratorSeatController` — never by `Match` or the game engine directly |

## Implementation decisions

- Package layout: `src/agent_game_framework/{core,connectors/{cli,mcp},agents,algorithm}` plus `examples/tictactoe/{game,algorithm}` for the throwaway reference game — note the reference game itself keeps its algorithm in a sibling module separate from its game logic, mirroring what a real game repo (e.g. `catan-agent/{game,algorithm}`) is expected to do (ADR-0001, ADR-0004, ADR-0007).
- `agent_game_framework.algorithm` hosts the `GameAlgorithm` Protocol and both composite `SeatController`s (`AdvisedLLMSeatController`, `AutoplayNarratorSeatController`) — these are framework code, reused unchanged by every game; a game repo's own `algorithm/` module only ever contains a `GameAlgorithm` *implementation*, never a new Protocol or a new composite controller (ADR-0004).
- `StateT`/`ActionT`/`ObservationT` are per-game typed data (dataclasses or pydantic models); the framework only requires them to be JSON-serializable via each game's `serialize`/`deserialize` (ADR-0003).
- `current_players(state) -> list[PlayerId]` returning more than one entry signals a simultaneous-move phase; Tic-Tac-Toe always returns exactly one, but the type is never narrowed to `PlayerId | None` at the contract level, so a later simultaneous-move game doesn't force a breaking change (ADR-0003).
- All illegal-input handling (human typos, AI backend returning an out-of-range action, a backend timeout) funnels through one `IllegalActionError`/`AgentTimeoutError` pair, raised by `Match`, never by a connector directly (ADR-0003, ADR-0005).
- Secrets: `OPENROUTER_API_KEY` from `.env`, excluded via `.gitignore`, never logged (Q12).

## Testing approach

The highest-leverage seam is the `GameEngine`/`Match` contract, since every
connector and controller sits on top of it — most tests target that seam
directly rather than going through a connector. CLI and MCP each get a thin
layer of their own tests (does the adapter translate correctly), not
duplicated rule tests. The all-AI and mixed-seat configurations are tested as
first-class cases, not incidental ones, since R1 is a named requirement.
Per-slice test plans are in SLICES.md.

## Assumed defaults

| ID | Assumed | Cost if wrong |
|----|---------|----------------|
| Q3 | Framework is a standalone package; real games live in sibling repos | Would need to re-split an accidentally-merged monorepo later |
| Q4 | Core contract supports N players/simultaneous moves from day one | Retrofitting after games are built against a 2-player-only contract would break all of them |
| Q5 | Game algorithms are standalone components (never owned by a game's own package), composed into a seat via the harness rather than exposed by `GameEngine` | High cost if wrong — this is the specific thing the user corrected mid-planning; getting it wrong again means real algorithm work (Catan/Poker) gets welded to game code and can't be swapped or third-party-authored |
| Q15 | Algorithm recommendations are computed automatically every turn, not called on-demand by the LLM as a tool | Low-medium cost — revisit if a real game's algorithm is too slow to run unconditionally every turn, or if an advised LLM needs to consult it conditionally |
| Q6 | Harness targets an abstract `SeatController`, not a concrete OpenRouter call | Low cost — the abstraction is cheap; skipping it would mean a rewrite when a second backend (voice, Claude Code) is added |
| Q7 | CLI before MCP, both thin adapters over one `Match` | Low cost — order is easily reversed since neither depends on the other |
| Q8 | Voice fully out of scope this milestone | Re-litigated naturally when a voice-driven game is actually planned |
| Q11 | `schema_version` on serialized state from day one | High cost if skipped and persistence is added later without it (silent corruption on format change) |

## Open risks

- The contract is validated only against Tic-Tac-Toe (strict turn order, full
  information, 2 players). Hidden information and simultaneous moves — needed
  for Poker/Catan and Wavelength respectively — are designed for (ADR-0003)
  but not proven until a real game is built against the contract. Earliest
  slice that would reveal a problem: the first real game's own Slice 1, not
  this milestone.
- `AlgorithmRecommendation`'s loose `scores`/`rationale` typing (ADR-0004) might
  be too unstructured for an LLM to reliably use once a real algorithm (Catan
  heuristic, poker equity) produces richer output than Tic-Tac-Toe's
  move-scored minimax. Revealed at Slice 4 only partially — real signal comes
  from the first real game's algorithm work.
- Always-automatic (never on-demand) algorithm computation (ADR-0004, Q15)
  could become wasted work per turn if a real game's algorithm is expensive —
  not observable with Tic-Tac-Toe's near-instant minimax, only once a slower
  real algorithm exists.
- `SeatController`'s `decide()` shape is designed around a single
  request/response per turn; a future streaming voice controller (partial
  audio in, partial audio out) may not fit it cleanly. Deferred risk, flagged
  in ADR-0005, not addressed this milestone.
