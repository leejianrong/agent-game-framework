# ADR-0004: Game algorithms are standalone, standardized components — never part of a game's own implementation, composed into a seat by the harness

- Status: Accepted (revised 2026-09-09, pre-implementation — no code exists yet against the prior version of this decision)
- Date: 2026-09-08 (revised 2026-09-09)
- Deciders: Jian

## Context

The user's second goal names three architectural pieces per game: game logic,
a pre-built AI algorithm/model producing strong-play signals, and the LLM agent
that consumes both. The user also flagged that Wavelength has no equivalent of
a Catan-strength heuristic engine or a poker solver — there's no well-defined
"optimal algorithm" for a hidden-target guessing game the way there is for
Catan or Poker. Baking a mandatory algorithm hook into the core `GameEngine`
contract (ADR-0003) would force Wavelength to implement a meaningless stub.

The first version of this ADR addressed that by making the hook optional, but
still framed it as something *the game* provides (`A game may provide zero,
one, or multiple advisors`). On review, the user was explicit that this framing
is wrong: an algorithm must **not** be part of a game's own implementation at
all — not owned by it, not shipped inside its package as "the" advisor. What's
wanted instead is a standardized wrapper so that when a real algorithm for a
game like Catan or chess is eventually built, it plugs in as a reusable,
independently-authored component — "like a standardized tool" — and, critically,
a third-party developer must be able to write their *own* algorithm for an
existing game (e.g. a better Catan heuristic) without touching that game's repo
at all.

The user also clarified two distinct ways an algorithm should be usable, both
needed:

1. **Advised** — an LLM makes the actual decision, informed by an
   automatically-computed algorithm recommendation it can choose to follow or
   override.
2. **Autoplay-narrated** — the algorithm makes the actual decision every time;
   the LLM has no say in which move is chosen and exists purely to narrate/
   banter about the move that was already made.

Between an on-demand tool-call (the LLM explicitly invokes the algorithm mid-
turn) and an auto-computed signal attached to every decision, the user leans
toward auto-computed — simpler, one request/response per turn, no tool-use
loop to build — while still wanting the "standardized tool" framing for how an
algorithm is *packaged and interfaced with*, not for how it's *invoked*.

## Decision

**The algorithm is a third pillar, independent of both `GameEngine` (ADR-0003)
and `SeatController` (ADR-0005).** It is defined once, in this framework, as a
Protocol that depends only on a game's public per-game types:

- `GameAlgorithm[ObservationT, ActionT]`:
  `recommend(observation: ObservationT, legal_actions: list[ActionT]) -> AlgorithmRecommendation[ActionT]`
- `AlgorithmRecommendation`: `best_action: ActionT` (mandatory — this is what
  makes it usable as an actual move, not just advisory text), plus a loosely-
  typed `rationale: str | None` and `scores: dict[ActionT, float] | None` for
  whatever extra structure a given algorithm wants to expose (a Catan heuristic
  might populate `scores` across candidate moves; a poker solver might use it
  for equity/pot-odds numbers).

A `GameAlgorithm` implementation touches nothing but a game's already-public
`ObservationT`/`ActionT` types (part of every game's `GameEngine` contract per
ADR-0003) — never the game engine's internal state representation, never its
rules code. This is what makes it possible for a third-party developer to
write an alternative algorithm for an existing game using only that game's
published types, with no access to or dependency on the game's own
implementation.

`SeatController` (ADR-0005) is simplified back to `decide(observation,
legal_actions) -> SeatDecision` — the core contract has **no knowledge of
algorithms at all**. Composition happens entirely inside specific
`SeatController` implementations, provided once by this framework and reused
by every game:

- `AdvisedLLMSeatController(llm, algorithm)` — auto-computes
  `algorithm.recommend(...)` every turn, attaches it to the inner LLM's
  context, and returns whatever action + banter the LLM ultimately decides on
  (it may follow or override the recommendation). Covers the "LLM actively
  decides, using the tool" case.
- `AutoplayNarratorSeatController(algorithm, narrator_llm)` — auto-computes
  `algorithm.recommend(...)` every turn and uses `best_action` **directly** as
  the move; the LLM is never asked to decide anything and is only given the
  observation + the chosen action + its rationale, to produce banter. Covers
  the "algorithm plays, LLM just banters" case.
- A bare `AlgorithmSeatController(algorithm)` (no LLM at all, `banter=None`) is
  the trivial degenerate case, useful as a fast deterministic bot and as the
  decision-making half that `AutoplayNarratorSeatController` wraps.

Any one `GameAlgorithm` implementation can be dropped into all three of these
without modification — write the algorithm once, get three deployment modes.

A game repo ships a default/reference `GameAlgorithm` implementation as a
sibling module, separate from its own game-logic module (e.g.
`catan-agent/algorithm/` alongside `catan-agent/game/`) — but this is only ever
*a* implementation, never *the* implementation. Anyone can publish their own
package implementing `GameAlgorithm` against that game's public types and wire
it into a `Match` the same way.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Mandatory algorithm hook on every `GameEngine` | Forces meaningless no-op implementations for games without a well-defined algorithm (Wavelength). |
| Algorithm as a `GameEngine`-owned hook the game exposes (the original version of this ADR) | This is exactly what the user rejected: it frames the algorithm as part of the game's own implementation, and makes "someone else's algorithm for my game" awkward — they'd need the game to expose a slot for it rather than just implementing a standalone Protocol against public types. |
| On-demand tool-call (LLM decides when to invoke the algorithm mid-turn, e.g. via function-calling or an MCP tool) | Rejected by the user for now in favor of auto-computed — one request/response per turn is simpler and there's no tool-use loop to build. Revisit if an advised seat's LLM needs to consult an algorithm conditionally rather than every turn. |
| One `SeatController` implementation with an "autoplay" boolean flag, instead of two distinct classes | A flag hides that these are genuinely different roles for the LLM (decision-maker vs narrator-only) behind one class's branching logic; two small, explicit classes are easier to reason about and to test in isolation. |

## Consequences

An algorithm for Catan or chess can be built, tested, and even authored by
someone else entirely independently of that game's own repo — it only needs
the game's public `ObservationT`/`ActionT` types. Both named usage modes
(LLM-advised, algorithm-autoplay-with-narration) are covered by two small,
reusable, framework-provided `SeatController` classes, not per-game glue code.
`SeatController`'s core contract stays as simple as it was before algorithms
existed at all.

The cost: because computation is always automatic (every turn, unconditionally)
rather than on-demand, an `AdvisedLLMSeatController` pays the algorithm's
compute cost every turn even on turns where the LLM would have ignored it
anyway — acceptable for a Tic-Tac-Toe minimax, revisit if a real game's
algorithm (e.g. a slow Catan search) makes that cost matter. `scores`/
`rationale` being loosely typed still means the framework guarantees a
recommendation arrives, not that an advised LLM uses it well.
