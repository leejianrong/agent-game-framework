# Questions

Statuses: `DECIDED` (user answered) · `ASSUMED` (default taken, correct it if
wrong) · `FORK` (waiting on the user) · `DEFERRED` (not needed this milestone).

## Open forks

<empty — both forks from round 1 were resolved>

## Register

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|--------------------|--------|
| Q1 | What language should the core framework be built in? | DECIDED | Python | ADR-0002 |
| Q2 | What's the first reference game to validate the contract on? | DECIDED | Tic-Tac-Toe, kept as a throwaway in-repo example (not a sibling game repo) | ADR-0007, SLICES.md V1 |
| Q3 | Where does game-specific code live relative to the framework? | ASSUMED | This repo is the reusable core framework/library only. Each real target game (Catan, Poker, Wavelength) becomes its own sibling repo under `agent-games/` depending on this one. The Tic-Tac-Toe reference lives inside this repo under `examples/` since it's discarded once the contract is proven, not a product. | ADR-0001 |
| Q4 | Should the core contract assume 2 players / turn order, or be general from day one? | ASSUMED | Design for N players and simultaneous-move phases (teams, hidden info) from day one. Generalizing now is nearly free; retrofitting after Poker/Catan/Wavelength-specific assumptions leak in is expensive. | ADR-0003 |
| Q5 | How does the "AI algorithm" component (Catan heuristics, poker equity, etc.) plug into the architecture, given Wavelength has no such algorithm, and without being fused into a game's own implementation? | DECIDED (user, mid-session, superseding the original ASSUMED answer) | A `GameAlgorithm` is a fully standalone component, defined once by the framework, depending only on a game's public observation/action types — never owned or exposed by `GameEngine`. Composition into a seat happens via one of two framework-provided `SeatController`s (see Q14b, Q15), never by the game itself. A third party can write their own `GameAlgorithm` for an existing game without touching that game's repo. No real algorithm is built this milestone; only the plumbing + a trivial minimax demo for Tic-Tac-Toe, in its own sibling module. | ADR-0004 |
| Q14b | Must the framework support both "LLM decides, algorithm advises" and "algorithm decides, LLM only narrates" as first-class modes? | DECIDED (user, mid-session) | Yes, both. `AdvisedLLMSeatController` (LLM is the decision-maker) and `AutoplayNarratorSeatController` (algorithm is the decision-maker, LLM only banters about the chosen move) are both framework-provided, reusable `SeatController` implementations composing the same `GameAlgorithm`. | ADR-0004 |
| Q15 | Should the LLM call the algorithm on demand (as a tool it chooses to invoke), or should the recommendation be computed automatically every turn? | DECIDED (user, mid-session) | Auto-computed every turn — simpler, one request/response per turn, no tool-use loop. On-demand tool-calling was considered and explicitly not chosen for this milestone (revisit if a real game's algorithm is too slow to run unconditionally, or an advised LLM needs to consult it conditionally). | ADR-0004 |
| Q16 | Where does a per-game algorithm implementation live, and can a third party build their own for an existing game? | DECIDED (user, mid-session) | Same repo as the game, but a separate sibling module from the game's own logic (e.g. `catan-agent/algorithm/` next to `catan-agent/game/`). This is only ever *a* reference implementation — the `GameAlgorithm` Protocol itself lives in the framework and depends only on the game's public observation/action types, so anyone can implement and wire in their own algorithm package against an existing game without modifying that game's repo. | ADR-0004 |
| Q6 | How does the LLM agent get invoked — direct API, or shelling out to an existing coding-agent CLI (Claude Code / Codex)? | ASSUMED | Harness is coded against an abstract `AgentBackend` interface. `OpenRouterBackend` is the first (and only, this milestone) concrete implementation — simplest, fully scriptable/testable without a human terminal in the loop. Claude-Code/Codex-as-backend and any TTS/voice backend become swappable implementations later, not a rewrite. | ADR-0005 |
| Q7 | CLI vs MCP — which connector first, and do they share logic? | ASSUMED | One core `Match` orchestrator/engine library. CLI and MCP (stdio transport) are both thin adapters over the same API — never divergent game logic. CLI first (fastest to validate human play + tests), MCP second. | ADR-0006 |
| Q8 | Is real-time voice (TTS/STT, Runpod-hosted models) in scope for this milestone? | ASSUMED | No — fully deferred. Only the text-banter half of the "feel human" goal is built this milestone (LLM produces a short free-text aside alongside its structured move). Voice is a future `AgentBackend`-adjacent concern, sketched as a forward note in ADR-0005 but not built. | PLAN.md §Scope |
| Q9 | Persistence / save-replay of matches? | DEFERRED | No storage requirement yet; state just needs to be JSON-serializable (already required for the connectors) so persistence can be bolted on later without a redesign. | n/a |
| Q10 | Multiplayer over a network (not just local process)? | DEFERRED | Out of scope. MCP stdio and local CLI cover this milestone; a networked transport is additive later given the connector/core split. | n/a |
| Q11 | Versioning of serialized game state? | ASSUMED | Every serialized state carries a `schema_version` field from day one, even with no persistence yet — cheap now, expensive to retrofit once real save data exists. | ADR-0003 |
| Q12 | Secrets handling (OpenRouter API key)? | ASSUMED | `.env`, excluded via `.gitignore`, never logged; no other sensitive data in this hobby project. | PLAN.md §Implementation decisions |
| Q13 | Failure behaviour when an agent/LLM backend errors or times out? | ASSUMED | `apply_action` raises a structured `IllegalActionError`/`AgentTimeoutError`; engine state is left unchanged on any failure — never a silently-guessed move, never a hang. Full "pause and hand off to a human" recovery UX is deferred past this milestone. | ADR-0003 |
| Q14 | Must a match support 1 human + N agents, and also all-AI matches with zero humans, as first-class runtime configurations? | DECIDED (user, mid-session) | Yes. Every seat is filled by a `SeatController` (human input is just one implementation of the same Protocol AI backends use); a `Match` is a seat -> controller mapping with zero required human seats, so humans-vs-agents and all-AI are the same code path, different configuration. | ADR-0005 |

## Coverage

| Category | Covered by |
|----------|-----------|
| Primary user and actors | PLAN.md §Users and actors, Q14 |
| Scope boundary | Q2, Q8, Q9, Q10, PLAN.md §Scope |
| Data model and identity | ADR-0003 |
| State and storage | Q9, Q11 |
| Concurrency and conflict | ADR-0003 (single-writer `Match` orchestrator) |
| Interfaces and contracts | Q7, ADR-0006 |
| Failure behaviour | Q13 |
| External dependencies | Q1, Q6, ADR-0002, ADR-0005 |
| Runtime and deployment | PLAN.md §Implementation decisions |
| Measurable success | SLICES.md (per-slice Demo + test plans) |
| Security and secrets | Q12 |
| Versioning and migration | Q11 |
