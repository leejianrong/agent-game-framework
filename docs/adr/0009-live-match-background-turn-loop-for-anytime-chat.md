# ADR-0009: `LiveMatch` runs a match's turn loop on a background thread so chat with a `Conversable` seat works at any time, including mid-decision

- Status: Accepted
- Date: 2026-09-09
- Deciders: Jian

## Context

ADR-0008 introduced `Conversable.respond(history, incoming) -> ConversationOutput`,
decoupled from `SeatController.decide()` specifically because "a human can
talk to an agent seat between turns, mid-turn, or not at all" — but it built
no runtime to actually make that true, and left it to whichever milestone
implements a `Conversable` (this one).

`Match.run_to_completion`/`play_turn` (ADR-0003) are synchronous: they call
`current_players()`'s seat controllers' `decide()` on the caller's own
thread, one at a time, and block until each returns. For an LLM-backed seat
(`OpenRouterBackend`), `decide()` is a blocking HTTP call taking roughly 1-3
seconds. If a CLI session wants to let a human type a chat message *during*
that window — not only when the CLI happens to be blocked on the human's own
`input()` prompt — something has to be running the match loop and the
chat-input loop concurrently. Nothing in the codebase did that before this
ticket: every connector so far has driven `Match` synchronously on its one
and only thread.

## Decision

A new, small, framework-level primitive: `agent_game_framework.core.live_match.LiveMatch`.
Construct it with an already-seated `Match` plus a `dict[PlayerId, Conversable]`
naming which seats can be chatted with; `.start()` runs `Match.run_to_completion`
on a background `threading.Thread`, immediately. Two operations are then
safe to call from any other thread while that background thread is running:

- `send_chat(to_player, text) -> ConversationOutput` — calls that seat's
  `Conversable.respond(history, incoming)` and appends both sides of the
  exchange to a per-seat conversation history, holding a per-seat
  `threading.Lock` for the duration (so two concurrent chat sends to the
  *same* seat serialize rather than corrupt that seat's history; different
  seats' locks are independent).
- `join()` — blocks until the match finishes, then re-raises any exception
  the background thread's `run_to_completion` call raised (e.g.
  `AgentTimeoutError`), so a caller's own error handling is unchanged from
  driving `Match` synchronously.

`Match`'s single-writer invariant (ADR-0003) is preserved exactly: only the
one background thread this class starts ever calls `submit_action`. Chat
never touches match state — `send_chat` reads nothing from `Match` at all,
only from its own per-seat conversation history — so there is no new writer
to reason about, only a second, independent kind of call (`respond`, never
`decide`) that can now happen concurrently with the first.

`LiveMatch` lives in `core/`, not the CLI connector, because it depends only
on `Match`/`SeatController`/`Conversable` — all game- and connector-agnostic
— and per ADR-0008's own framing ("a human can talk to an agent seat between
turns, mid-turn, or not at all"), this is a capability every future connector
(not just this CLI) should get for free, not a CLI-specific hack. What *is*
connector-specific, and stays in `cli.py`, is the policy for multiplexing one
real terminal's stdin between "fulfill a pending move" and "send a chat
message" — that's presentation, not orchestration, and ADR-0008 already
assigns exactly this kind of I/O-adapter responsibility to the connector.

**One accepted, not hidden, tradeoff.** A human chatting with a seat at the
exact moment that seat's own `decide()` call is in flight produces two
concurrent HTTP calls to the same backend (a move-decision call, and a
chat-response call). `OpenRouterBackend`'s `httpx2.Client` supports
concurrent requests fine, but the two calls are independent round trips: the
chat reply has no way to know a move is about to land, and vice versa. For a
two-seat, turn-based game with short LLM latency this is a minor, cosmetic
coherence gap, not a correctness bug — nothing about match state or move
legality is affected — so it's accepted as-is rather than solved with, say,
a single-flight lock shared between `decide()` and `respond()` for the same
seat (which would silently reintroduce the "mid-turn" chat delay ADR-0008
and this ADR both exist to remove).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Keep chat CLI-only: multiplex stdin only when the *human* is prompted (i.e., only on the human's own turn), no background thread at all | Simpler, but contradicts the explicit requirement that chat work "anytime, including [the LLM's] turn" — a human would still be locked out for the ~1-3s an opponent's `decide()` call is in flight. |
| Make `Match` itself async/threaded internally | Changes `Match`'s own contract (ADR-0003's synchronous, single-writer design) for every caller, including ones (tests, MCP, a future non-interactive batch runner) that have no use for concurrent chat at all. `LiveMatch` gets the same effect by wrapping `Match` unchanged, opt-in per caller. |
| A single-flight lock per seat shared between `decide()` and `respond()`, serializing chat and move-decisions | Removes the "mid-turn" chat capability this ADR exists to add — a chat message sent while the seat is deciding would simply queue behind that decide() call, indistinguishable from the status quo ADR-0008 already rejected. |

## Consequences

Chat is a real, general-purpose framework capability (`core/live_match.py`),
usable by any future connector wired to a `Conversable` seat, not a
CLI-only trick. The CLI's own contribution is a single stdin-reading loop
that routes each line to whichever is currently pending: fulfilling a
human's move if one was requested, chat otherwise — implemented without
`HumanCLIController` itself ever calling `input()` in this mode, so there is
exactly one stdin reader, never two threads racing on the same file
descriptor.

The cost: this is the first concurrency this codebase has ever had to
reason about testably. Tests for `LiveMatch` use `threading.Event`-based
synchronization to force deterministic overlap (e.g. "chat resolves while a
seat's `decide()` is still blocked"), never a `time.sleep`-based race, per
this repo's existing determinism discipline (see `AGENTS.md`). Composite
seat controllers (`AdvisedLLMSeatController`, `AutoplayNarratorSeatController`,
ADR-0004) each grow a small `respond()` pass-through to their inner LLM, so
chat continues to "see through" seat composition exactly the way `decide()`
already does — a seat wrapped in either composite is exactly as chattable as
a bare `llm:openrouter/<model>` seat.
