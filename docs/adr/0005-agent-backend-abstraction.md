# ADR-0005: One SeatController abstraction covers humans and every AI backend; OpenRouter is the first AI implementation

- Status: Accepted
- Date: 2026-09-08
- Deciders: Jian

## Context

The user named two different ways an LLM could drive an agent player: a direct
OpenRouter API call, or piping output from an interactive coding-agent CLI
(Claude Code, Codex) acting as the "LLM." These have very different operational
shapes — one is a stateless HTTP call usable in an automated test, the other
assumes an interactive terminal/session. The user also wants, eventually, the
agent to banter over voice, and to support both a text+TTS pipeline and a
native multimodal (audio-in/audio-out) pipeline — how that's shaped is decided
separately in ADR-0008 and does not affect this ADR's `decide()` contract.

Separately, the user was explicit that a match must support any mix of seats —
1 human + N AI agents, or zero humans and all AI seats (e.g. for testing, or a
future spectator mode) — not just a fixed "1 human vs 1 agent" shape. If human
input were wired into the CLI as a special case sitting outside the AI-backend
abstraction, an all-AI match would need a separate code path, and "how many
humans" would stop being a runtime choice.

## Decision

Every seat in a `Match` is filled by an implementation of one Protocol,
`SeatController`:

- `decide(observation, legal_actions) -> SeatDecision`
  (`SeatDecision` = a structured legal action + an optional short free-text
  banter string)

This Protocol has **no knowledge of game algorithms** — a `GameAlgorithm`
(ADR-0004) is never passed into `decide()`. Any algorithm composition (an LLM
advised by an algorithm's recommendation, or an algorithm that plays while an
LLM only narrates) happens entirely *inside* a specific `SeatController`
implementation, which internally calls out to a `GameAlgorithm` as needed
before returning a `SeatDecision` — the outer contract Match/CLI/MCP see is
identical either way.

A human player is just another `SeatController` implementation
(`HumanCLIController`: prints the board/observation, prompts on stdin, returns
the parsed move with no banter). `AgentBackend` is the sub-family of
`SeatController` implementations backed by an LLM — `OpenRouterBackend` is the
only concrete one built this milestone (stateless, works headless in
CI/integration tests, needs only an API key, no local GPU). Non-LLM
controllers (a random-move bot, or a bare `AlgorithmSeatController` per
ADR-0004) are `SeatController` implementations too, with no LLM involved at all.

Because every seat is assigned a `SeatController` independently, a `Match` is
constructed as a seat -> controller mapping with **zero required human
seats** — 1 human + N agents and all-AI (0 humans) are both just different
mappings, not different code paths. Claude-Code/Codex-as-controller is a
future `SeatController` implementation, not an architectural change, when it's
eventually built. Voice/conversation is deliberately **not** modeled as a
`SeatController` variant at all — see ADR-0008's `Conversable` capability,
which a `SeatController` implementation may additionally provide.

Illegal or malformed decisions from any controller (an action outside
`legal_actions`, or a response that fails to parse) are rejected by the `Match`
orchestrator identically regardless of controller kind — via
`IllegalActionError` — never silently coerced into a legal move, and never
handled differently because the seat happens to be human.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Human input wired directly into the CLI, separate from an `AgentBackend` abstraction | Cheapest to write first, but makes "all seats AI, no human" a second code path instead of a natural case of "assign 0 human controllers" — directly contradicts the requirement that human/agent seat count be a runtime choice. |
| Build directly against the OpenRouter API in the harness, no abstraction | The user explicitly wants to try Claude-Code/Codex-as-agent and eventually voice — locking to one concrete backend means a harness rewrite for each, not an added implementation. |
| Build the Claude-Code/Codex-CLI backend first | Harder to test headlessly/deterministically (assumes an interactive session) and doesn't unblock the OpenRouter path the user already leans toward for "real-time." Starting with the stateless option de-risks the harness contract first. |

## Consequences

A match with any number of human seats from 0 to N is a configuration choice
(which `SeatController` fills each seat), never a special-cased code path —
directly satisfying the "1 human + N agents, or all-AI" requirement. Swapping
or adding an AI access method later (Claude Code as the driver) is an additive
`SeatController` implementation, not a harness rewrite. Voice and multimodal
conversation are resolved separately by ADR-0008's `Conversable` capability,
which keeps `decide()`'s contract exactly as simple as it is today — no
revision needed here once a voice-capable seat is actually built.
