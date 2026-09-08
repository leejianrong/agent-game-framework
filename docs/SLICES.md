# Agent Game Framework: Slices

Vertical increments. Each ends in something you can demonstrate. Slice 1
confronts the riskiest unknown: whether the core contract (ADR-0003) and the
seat-controller abstraction (ADR-0005) actually support arbitrary human/AI seat
mixes, including zero humans, without special-casing.

## V1: Core engine + CLI, any mix of human/bot seats

**Delivers:** R0, R1, R4 (partial — CLI only), R5, R6, R7

**Build plan**

1. Package skeleton: `pyproject.toml`, `src/agent_game_framework/` layout — installable from the first commit, not retrofitted once there's "enough" code to bother.
2. `core`: `GameEngine` Protocol, `PlayerId`, `IllegalActionError`, `Match` orchestrator (single writer, drives the turn loop via `current_players`).
2. `core`: `SeatController` Protocol + `SeatDecision` type.
3. `examples/tictactoe`: `TicTacToeEngine` implementing `GameEngine` (board state, X/O actions, win/draw detection, `schema_version` on serialize).
4. `agents`: `HumanCLIController` (prints board, prompts stdin, validates against `legal_actions` before returning) and a `RandomBotController` (uniform-random legal move) — both `SeatController` implementations.
5. `connectors/cli`: `agf play tictactoe --seat <id>=<human|bot:random> [...]` — arbitrary number of seats, arbitrary controller mix, `--json` state-dump flag.
6. Wire the seat map into `Match` with zero required human seats.

**Demo:** Run `agf play tictactoe --seat X=human --seat O=bot:random` and play a full game via the terminal to a win/draw. Then run `agf play tictactoe --seat X=bot:random --seat O=bot:random` with no human input at all and watch it play itself to completion, printing each move.

**Rests on assumptions:** Q4 (N-player/simultaneous-capable contract) — Tic-Tac-Toe only exercises the 2-player, strict-turn-order case, so this slice can't prove the simultaneous-move path works, only that it compiles/type-checks against the Protocol.

### Test plan

#### End-to-end

- `pip install` this package (editable, from a scratch venv) succeeds and `agf --help` runs, proving R6 (installable from a sibling repo) rather than just "runnable in place."
- CLI, human vs bot: scripted stdin drives a full game to a win; final printed board matches the winning line.
- CLI, all-bot (zero human seats): a full game runs to completion (win or draw) with no stdin input required, proving R1's "0 humans" case end-to-end, not just at the type level.
- CLI rejects an out-of-range/occupied-cell move typed by a human seat with a clear error and does not advance the turn.

#### Integration

- Drive a full game programmatically through `Match` (no CLI) for: human-seat-simulated-by-fixture vs bot, and bot vs bot; assert a winner or draw is reached and `is_terminal` becomes true exactly once.
- `Match.apply_action` with an illegal action raises `IllegalActionError` and leaves `Match`'s state byte-for-byte (via `serialize`) unchanged.

#### Unit

- `TicTacToeEngine.legal_actions` excludes occupied cells.
- `TicTacToeEngine.winners` detects all 8 winning lines and returns `[]` on a full-board draw.
- `serialize`/`deserialize` round-trips a mid-game state, including `schema_version`.
- `RandomBotController.decide` only ever returns actions from the `legal_actions` it was given.

## V2: MCP connector

**Delivers:** R0, R4 (complete)

**Build plan**

1. `connectors/mcp`: stdio MCP server exposing `get_observation`, `list_legal_actions`, `submit_action`, `get_state_dump` tools, backed by the same `Match` class from V1 — no game logic in this layer.
2. Seat-to-controller assignment for an MCP-driven seat: the MCP client itself acts as the controller for whichever seat(s) it calls `submit_action` for; other seats can still be filled by `RandomBotController` from V1 so a full game can complete without a second MCP client.
3. A test-only MCP client harness (used by the integration tests below) that connects over stdio and plays a scripted game.

**Demo:** Start the MCP server for a Tic-Tac-Toe match with one seat assigned to a bot; connect an MCP client (a small script, or Claude Code itself pointed at the server) that calls `get_observation` / `list_legal_actions` / `submit_action` in a loop until `get_state_dump` reports the game is terminal.

**Rests on assumptions:** Q7 (CLI/MCP as thin adapters over one `Match`) — if wrong, this slice would have needed its own copy of the rule-checking logic instead of reusing V1's.

### Test plan

#### End-to-end

- The test-only MCP client harness plays a full game against a `RandomBotController` seat entirely over the MCP stdio transport and reaches a terminal state matching what an equivalent CLI-driven game would produce from the same random seed.

#### Integration

- `submit_action` with an illegal action returns a structured MCP tool error (not a crash, not a silently-ignored call) and `get_state_dump` shows the state unchanged.
- `get_observation` for a given seat never includes information a `GameEngine.observation_for` call would hide for that seat (for Tic-Tac-Toe this is vacuous — full information — so this test doubles as a placeholder that must be revisited once a hidden-information game exists).

#### Unit

- MCP tool input schemas reject a malformed `submit_action` payload (wrong type, missing field) before it reaches `Match`.

## V3: LLM seat controller with banter (OpenRouter)

**Delivers:** R1 (complete — 3-way human/AI/all-AI matrix), R3

**Build plan**

1. `agents`: `AgentDecision`-producing `OpenRouterBackend` implementing `SeatController` — sends the observation + legal actions as a constrained tool-call/function-call request, parses the response into a legal action plus a short free-text banter string.
2. `Match`/CLI: reject and re-prompt-once (then fail with `AgentTimeoutError`/`IllegalActionError`) on a malformed or illegal `OpenRouterBackend` response, per ADR-0005 — never silently coerce.
3. CLI: `--seat <id>=llm:openrouter/<model>` option wired to `OpenRouterBackend`.
4. Banter rendering: CLI prints the seat's banter line alongside its move (text only, no TTS).

**Demo:** Run `agf play tictactoe --seat X=human --seat O=llm:openrouter/<model>` and play a full game against a live LLM opponent that also prints a short in-character line each turn. Then run `agf play tictactoe --seat X=llm:openrouter/<model> --seat O=bot:random` with zero human seats and watch an LLM play unattended to completion.

**Rests on assumptions:** Q6 (`SeatController` abstraction over concrete OpenRouter calls) — validated directly by this slice, since `OpenRouterBackend` is written as one more `SeatController` implementation with no special-casing in `Match` or the CLI.

### Test plan

#### End-to-end

- Human vs `OpenRouterBackend`: scripted human input plus a live (or recorded/replayed) OpenRouter response drives a full game to completion, with a banter line printed each AI turn.
- All-AI, no human seats, one of which is `OpenRouterBackend`: a full game completes unattended.

#### Integration

- `OpenRouterBackend.decide` given a mocked API response containing an illegal action causes `Match` to raise `IllegalActionError`, exactly as a human's illegal move would (same code path, per ADR-0005) — proven by asserting both go through the same exception type and leave state unchanged.
- A mocked API timeout/error surfaces as `AgentTimeoutError` rather than hanging the turn loop.

#### Unit

- The prompt/response parser extracts a legal-shaped action and a banter string from a well-formed tool-call response, and raises a parse error (not a crash) on a malformed one.

## V4: Standalone game algorithm, in two composition modes

**Delivers:** R2

**Build plan**

1. `algorithm`: `GameAlgorithm[ObservationT, ActionT]` Protocol (`recommend(observation, legal_actions) -> AlgorithmRecommendation`) and `AlgorithmRecommendation` (`best_action` mandatory, plus loosely-typed `rationale`/`scores`). Lives entirely in the framework, with zero dependency on `GameEngine` or any specific game.
2. `examples/tictactoe/algorithm/` (a sibling module to `examples/tictactoe/game/`, never importing its internals): a minimax-based `GameAlgorithm` returning the exact best move plus a win/lose/draw evaluation per legal move (3x3 is fully solvable) — built only against Tic-Tac-Toe's public observation/action types, to prove a third party could write this without repo access to the game logic.
3. `algorithm`: `AdvisedLLMSeatController(llm, algorithm)` — auto-computes a recommendation every turn, attaches it to the inner LLM's context, returns whatever action + banter the LLM decides on.
4. `algorithm`: `AutoplayNarratorSeatController(algorithm, narrator_llm)` — auto-computes a recommendation every turn and uses `best_action` directly as the move; the narrator LLM is given the observation + chosen action + rationale and returns banter only, never a move.
5. CLI: seat modifiers wiring both composite controllers (e.g. `--seat X=llm:openrouter/<model>:advised-by=algo:tictactoe-minimax` and `--seat O=algo:tictactoe-minimax:narrated-by=llm:openrouter/<model>`) — the plain unadvised `--seat=llm:...` form from V3 keeps working unchanged.

**Demo:** Run a match with one `AdvisedLLMSeatController` seat and one `AutoplayNarratorSeatController` seat (both wrapping the same minimax `GameAlgorithm`). Via printed banter/decision logs, show: the advised seat's LLM request payload contained the minimax recommendation and its final move may differ from that recommendation; the autoplay seat's move always equals the algorithm's `best_action` exactly, with the LLM's output containing only banter, never a different action.

**Rests on assumptions:** Q15 (auto-computed every turn, not on-demand) — this slice is the first real test of whether that's cheap enough to be a non-issue (Tic-Tac-Toe's minimax is near-instant; a slower real-game algorithm might not be). Q5/Q16 (algorithm as a fully standalone, third-party-authorable component) — validated directly by building the Tic-Tac-Toe algorithm against only its public types in a separate module.

### Test plan

#### End-to-end

- A match with one `AdvisedLLMSeatController` seat and one `AutoplayNarratorSeatController` seat completes; the autoplay seat's every move exactly matches its algorithm's `best_action` for that turn.
- The advised seat's logged request payload contains the `AlgorithmRecommendation` each turn; a plain unadvised `--seat=llm:...` seat (from V3) has no such payload.

#### Integration

- `AdvisedLLMSeatController.decide` calls `algorithm.recommend` exactly once per decision (not once per legal action) and passes it through to the inner LLM unmodified.
- `AutoplayNarratorSeatController.decide` never asks its narrator LLM to choose an action — the returned `SeatDecision.action` is always `recommendation.best_action`, sourced directly from the algorithm, regardless of what the narrator LLM's text output contains.
- A seat with no algorithm configured (a plain `OpenRouterBackend` from V3) never has any `GameAlgorithm` called — no code path requires one to exist.

#### Unit

- The minimax `GameAlgorithm` returns a correct `best_action` and win/lose/draw evaluation for a set of known Tic-Tac-Toe positions, including one where only one non-losing move exists.
- The minimax module has zero imports from `examples/tictactoe/game/` — a static check that the algorithm depends only on the game's public observation/action types, not its internals.
