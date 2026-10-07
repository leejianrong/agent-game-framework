# Brief for the text/audio-to-avatar project

This is for the team building the avatar project (text to audio + video for LLM players, and audio to avatar video for humans who just speak). It explains what it needs to plug into, what we want from it, and some options for how to build it. Nothing here is final, so push back where something doesn't fit.

## Why this exists

We're building a set of games where any seat can be a human, a scripted bot, or an LLM, including matches with no human at all. The goal is for the LLM seats to feel like people at the table: they talk, react, bluff and tease, and a human can talk back. Text banter already works. What's missing is a voice and a face.

The avatar project is deliberately separate from the game code. Games shouldn't know what a renderer is, and the avatar project shouldn't know what Catan is. The two meet at a small interface (described below).

## The games

Everything runs on `agent-game-framework`, a Python package (this repo). A game implements one `GameEngine` contract (state, legal actions, per-player observations, apply action) and gets human, bot and LLM seats, a CLI and an MCP server for free. Each real game lives in its own sibling repo and depends on the framework (ADR-0001).

What exists today:

- **Tic-Tac-Toe** is the reference game that proved the framework. It supports human vs LLM, all-LLM matches, an LLM advised by minimax, and minimax playing every move while an LLM narrates. It's a test bed, not a product.
- **LLM chat** (ADR-0008, ADR-0009) is built for text. A human can chat with an LLM seat at any time, including while that seat is still deciding its move, because the match runs on a background thread.

What's planned, each as its own repo and its own planning pass:

- **Wavelength.** One player (the psychic) sees a hidden target on a spectrum and gives a clue; the others guess where it sits. The spoken clue is the game, so voice matters most here. It's also the first game with hidden information.
- **Codenames.** Spymasters give one-word clues to steer teammates towards the right words. Another game where what's said is the move.
- **Poker.** Hidden cards, bluffing, and table talk. Tells and timing matter.
- **Catan.** Trading and negotiation between players, with a lot of free conversation around the actual moves.

## What the avatar project is for

1. Give an LLM seat a voice and a face, driven by text the LLM already produces.
2. Let a human talk to the table by voice, turn their speech into text (or pass the audio through), and optionally show them as an avatar to other viewers.
3. Work with any game without game-specific code.

The human audio-to-avatar feature is mostly presentation. The game itself only needs the transcript (or the raw audio, if the model on the other end is multimodal).

## Broad requirements

### Game-agnostic

The project must not import anything from a game or from the framework's game code. It consumes a small set of events and produces media. Anything a game wants to express (a clue, a bluff, a trade offer) arrives as text plus optional hints, never as game state.

### Two directions, kept separate

- **Output (LLM to viewer):** text in, synchronised audio and video out.
- **Input (human to table):** microphone audio in, a transcript out (and optionally an avatar video of the human for other viewers).

These can ship independently. Output is the more valuable half, so build it first.

### Streaming first

The LLM's reply arrives as a stream of text. Audio should start as soon as the first sentence is ready, not after the whole reply. The project should accept text in chunks and emit audio and video chunks as they're ready.

### Latency budget

A conversation feels natural when the avatar starts speaking within roughly a second of the text arriving. We'd like the team to measure and report time to first audio and time to first video frame, and to tell us honestly where they land. Games can mask some delay with a "thinking" animation, so the avatar needs idle and thinking states as well as a speaking one.

### Lifecycle events we need back

The game has to be able to wait for, or at least react to, what the avatar is doing. So the project should emit:

- `speech_started` and `speech_finished` (with an id matching the utterance we sent)
- `speech_interrupted` (if a human talks over the avatar, or we cancel it)
- `error` with a reason, so a failed render never stalls a match

### Cancellation and interruption

We need to be able to cut an utterance off mid-sentence (a new game event makes the old line stale, or the human started talking). Cancelling must stop audio and video quickly and leave the avatar in a clean idle state.

### Expression hints

Text alone loses tone. The input should accept optional hints alongside the text, for example `emotion: smug`, `emotion: worried`, or `intensity: 0.7`. We'd rather agree a small fixed vocabulary (five to eight emotions) than pass free text. If a hint is missing or unknown, the avatar falls back to neutral.

### One avatar per seat, with a persona

Each seat gets its own identity: a voice, a face or character, and optionally a speaking style. Two LLM seats in the same match must be visually and audibly distinct. Identities should be configurable by name, so a game config can say `seat 2 uses persona "ada"`.

### Swappable parts

Speech-to-text, text-to-speech and the renderer should each sit behind their own interface. We expect to change vendors, and we want to run cheap or local options in development and better ones for demos.

### Testable without GPUs or API keys

The framework's tests never call a paid or non-deterministic service (see AGENTS.md). We'd like the same here: a fake TTS that returns canned audio, a fake renderer that returns a placeholder, and a recorded-event test mode. The framework side will do the same with a fake avatar.

### Runs headless

It should work with no window, so it can run on a server or in CI, and be viewed through a browser or a video stream.

### Fits a no-human match

A match with several LLM seats and no human should work. Some of those avatars may never be watched live, so rendering should be optional per seat (audio only, or nothing).

## The interface we'll plug into

The framework doesn't have this yet. We plan to add it (as an ADR, working title ADR-0010) once the shape is agreed. This is our current thinking, and the avatar team's input is welcome.

**Events from the framework to the avatar project**, one stream per match:

- `utterance` with `seat_id`, `utterance_id`, `text` (or text deltas), optional `emotion`, and a `kind` (`banter`, `clue`, `table_talk`)
- `cancel` with an `utterance_id`
- `turn_started` and `turn_ended` with `seat_id` (so the avatar can switch to a thinking pose)
- `game_over` with an outcome hint (won, lost, drew)

**Events from the avatar project back to the framework:**

- `speech_started`, `speech_finished`, `speech_interrupted` (keyed by `utterance_id`)
- `human_utterance` with `seat_id`, `text` (the transcript), optionally the raw audio
- `error`

Utterance text is already decided before it reaches the avatar. The avatar never decides what is said and never changes game state. Clues in games like Wavelength are real game actions that go through the normal action path, and the avatar only gets a copy to speak.

Two ways it could be wired:

- **In-process Python.** The avatar project exposes a class that implements a `Presenter` protocol (the framework side of the events above). Simple, fast, good for development.
- **Over a WebSocket.** The framework publishes the same events as JSON and the avatar service subscribes. Better if rendering runs on a GPU machine or in a browser. This also gives us a replayable event log.

The event shapes should be identical either way, so we can start in-process and move to the network without rewriting either side.

## Options for building it

These are candidates to evaluate, not recommendations to adopt blindly. Vendor products change quickly, so please verify current pricing, licensing and realtime support before committing.

### Where the avatar comes from

**Option 1: a rigged character driven by audio (recommended starting point).** A 3D (VRM models rendered with three-vrm in the browser) or 2D (Live2D) character, animated from the TTS audio using visemes or amplitude, plus emotion presets. Cheap, very low latency, runs in a browser tab, easy to give each seat a distinct look. It looks like a stylised character, not a person. For a table of game opponents, I think that is a good thing: it avoids the uncanny valley and lets each seat have a clear personality.

**Option 2: a hosted streaming avatar service.** Products such as HeyGen's streaming avatars, D-ID, Tavus and Simli take text or audio and return realistic talking-head video over WebRTC. Highest realism for the least engineering, but you pay per minute, depend on the vendor's latency and uptime, and have less control over persona and cancellation. Worth a trial for a demo.

**Option 3: self-hosted audio-driven face models.** Open models for lip-sync and talking heads, such as Wav2Lip, MuseTalk, SadTalker and LivePortrait, run on our own GPU (a rented pod would do). Realistic output and no per-minute fee, but real latency, GPU cost, uneven quality, and licence terms to check (some are research-only). I'd treat this as an experiment after Option 1 works, not a starting point.

### Where the voice comes from

- **Text to speech:** hosted (ElevenLabs, OpenAI, Cartesia) for quality and streaming; local (Piper, Kokoro) for free development and offline tests. Cartesia-style streaming TTS matters most for the latency budget.
- **Speech to text:** a hosted streaming service (Deepgram, for example) for speed, or Whisper (via faster-whisper) locally. We need partial transcripts while the human is still talking, but only final ones affect the game.
- **Native speech-to-speech models** (OpenAI's realtime API, Gemini Live, and similar): skip separate STT and TTS entirely. ADR-0008 already allows this as a second pipeline, where the model takes audio and returns audio. The catch is that we lose the plain-text transcript the game and the logs rely on, so the project should still be able to emit text alongside any audio it produces.

### How to deliver it

- **Browser renderer, project streams audio and control events.** Matches Option 1 best. The browser does the drawing, the server only sends audio and cues.
- **Server renders video, streams it over WebRTC.** Needed for Options 2 and 3. More moving parts, but the client can be a plain `<video>` tag.
- **Audio only (no video).** A legitimate first milestone. It gets voice working end to end with almost no rendering work, and every later step builds on it.

### Suggested path

1. Audio only: streaming TTS from utterance events, with start, finish and cancel working and a fake backend for tests.
2. A browser avatar (Option 1) with visemes and emotion presets, wired to the same events.
3. Human voice input with streaming STT, feeding `human_utterance`.
4. Evaluate Options 2 and 3 for a more realistic look if the stylised avatars aren't enough.

## Open questions

- Does a game wait for an avatar to finish speaking before the next AI move, or run ahead? We lean towards a per-game setting, defaulting to waiting for speech between turns but never blocking a human's input.
- How many seats might be rendered at once on one machine?
- Do human players want to see their own avatar, or only hear and be heard?
- Who owns the persona definitions (voice, look, style): the avatar project, or each game's config?
- Hosted services mean player audio leaves the machine. Is that acceptable, and should local-only be a supported mode from the start?

## Where to read more

- `docs/adr/0008-conversable-capability-for-voice-and-multimodal.md` for the `Conversable` capability and the two voice pipelines.
- `docs/adr/0009-live-match-background-turn-loop-for-anytime-chat.md` for how chat runs during a match.
- `docs/adr/0001-repo-and-package-boundary.md` for how game repos depend on the framework.
- `docs/PLAN.md` for the framework's overall scope.
