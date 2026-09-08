# ADR-0008: Conversation is a separate, optional `Conversable` capability — decoupled from `SeatController.decide()`, modality-agnostic by design

- Status: Accepted
- Date: 2026-09-09
- Deciders: Jian

## Context

The "feel like a real human" goal (PLAN.md §Problem, §Users and actors) has
two distinct threads that this framework had, until now, silently conflated:
making a legal game move, and holding a conversation with the human player.
ADR-0005 modeled only the first — `SeatController.decide(observation,
legal_actions) -> SeatDecision`, where `SeatDecision` carries one optional
free-text banter line, produced once per turn, alongside the move. ADR-0005
also hand-waved the eventual voice story as "a future TTS-producing
`SeatController` implementation," without specifying its shape.

That hand-wave doesn't survive contact with a real requirement: the user wants
to support **two different voice architectures**, chosen per seat, not
committed to once for the whole framework:

1. **Text pipeline** — human speech is transcribed to text (STT) before it
   reaches the model; the model reasons and responds in text only; that text
   is synthesized to speech (TTS) afterward. Game state and the model's
   decisions/actions stay text throughout.
2. **Multimodal pipeline** — human speech is fed to the model as raw audio
   directly (no separate STT step), because the model itself is multimodal
   (e.g. a realtime audio-capable model); it may respond with audio directly
   (no separate TTS step) or with text that then still needs TTS.

Neither fits into `decide()`/`SeatDecision` as specified:

- **Cadence mismatch.** `decide()` fires once per game turn and returns
  exactly one action. A conversation is continuous and asynchronous — a human
  can talk to an agent seat between turns, mid-turn, or not at all on a given
  turn. Tying conversation to the turn loop means either starving it (only one
  line per turn) or overloading `decide()` with concerns that have nothing to
  do with legal-move validation.
- **Modality mismatch.** `SeatDecision.banter` is typed as text. A multimodal
  pipeline's natural output is audio; forcing it through a text-only field
  means every multimodal implementation has to fake a text intermediate even
  when the underlying model never produced one.

## Decision

A new Protocol, independent of `SeatController` and `GameEngine` alike:

```python
Conversable.respond(history: list[ConversationTurn], incoming: ConversationInput) -> ConversationOutput
```

- `ConversationInput` and `ConversationOutput` are modality-tagged union types:
  `TextTurn(text: str)` or `AudioTurn(audio: bytes, sample_rate: int, format: str)`.
- `ConversationTurn` is whichever of the two actually occurred, kept as
  conversation history — a `Conversable` implementation is free to store audio
  turns as audio, not forced to transcribe for its own history.

`SeatController` is untouched by this ADR: `decide()` keeps deciding moves,
`SeatDecision` keeps its own short per-turn banter field for the simple
"one canned line when I move" case built in Slice 3 (ADR-0005) — that case
doesn't disappear, it's just no longer the *only* way an agent talks. A
`SeatController` implementation *may* additionally implement `Conversable`
(any LLM-backed one plausibly will); a plain bot or algorithm-driven seat
(ADR-0004) has no reason to and simply doesn't.

A connector-owned **voice I/O adapter** — not the model, not the framework
core — is responsible for turning a human's raw microphone input into a
`ConversationInput` and a `ConversationOutput` back into what the human hears,
and this is where the two pipelines actually diverge:

- Text pipeline: adapter runs STT on the mic input to produce a `TextTurn`,
  calls `respond()`, gets back a `TextTurn`, runs TTS on it before playback.
- Multimodal pipeline: adapter wraps the raw mic bytes directly as an
  `AudioTurn`, calls `respond()` against a multimodal-model-backed
  `Conversable`, and either plays an `AudioTurn` result back directly or falls
  through to TTS if the model returned a `TextTurn` instead.

Which pipeline is in play is entirely a property of *which `Conversable`
implementation is wired into a seat* — the same composition pattern already
used for `GameAlgorithm` (ADR-0004) and for swapping `SeatController` backends
(ADR-0005). Nothing about `Match`, `GameEngine`, or `SeatController` needs to
know or care which one a given seat uses, and both can coexist in the same
match (one seat text-piped, another multimodal).

No `Conversable` implementation, and no voice I/O adapter, is built in this
milestone (PLAN.md §Scope already excludes voice/TTS/STT entirely) — this ADR
fixes the *shape* now, cheaply, so that when a voice milestone is actually
planned, `SeatController` doesn't need to be redesigned to fit it.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Extend `SeatDecision.banter` to accept either text or audio, keep it inside `decide()` | Doesn't fix the cadence mismatch — conversation would still be limited to once per game turn, which isn't a conversation. |
| Commit to one voice architecture (e.g. always STT → text-only model → TTS) | Directly contradicts the requirement to support both a text pipeline and a native multimodal pipeline, chosen per seat. |
| Model conversation as another `SeatController` (a seat exists purely to converse, separate from the seat that moves) | Conflates "which entity is talking" with "which entity is playing" — in every real case here they're the same agent, just doing two different things on two different cadences. A capability a `SeatController` optionally also has is the simpler model. |

## Consequences

Both the text+TTS pipeline and a native multimodal pipeline are supported as
swappable `Conversable` implementations, resolving the "future TTS-producing
backend" hand-wave in ADR-0005 §Decision and §Consequences with a concrete,
modality-agnostic shape. Conversation and move-decisions are cleanly
separable, so a future streaming/realtime `Conversable` implementation doesn't
force any change to `SeatController.decide()`'s already-simple, already-tested
contract (ADR-0005).

The cost: this is a second, independently-evolving Protocol to keep in sync
with `SeatController` conceptually (an agent seat now potentially has two
separate "personalities" — its decision logic and its conversational logic —
that a game's harness config must wire together coherently, e.g. so an
advised-LLM seat's conversational responses don't contradict the move it just
made). This coherence isn't enforced by the type system; it's a build-time
concern for whichever milestone actually implements a `Conversable`.
