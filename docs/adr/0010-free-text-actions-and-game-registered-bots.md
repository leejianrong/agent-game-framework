# ADR-0010: Free-text actions, and bots registered by the game

- Status: Accepted
- Date: 2026-10-14
- Deciders: Jian (requested by Wavelength planning, `leejianrong/wavelength` ADR-0004)

## Context

`legal_actions` was always a finite list, and three adapters assumed it: `OpenRouterBackend` forced `action` to a JSON-schema `enum`, `HumanCLIController` matched typed input against `str(action)`, and the CLI's live-chat loop did the same. A game whose move is arbitrary text (a Wavelength clue, a Codenames clue word) could not be played by an LLM or a human. Separately, `build_controller` hardcodes `human` and `bot:random`, and `RandomBotController` cannot write text, so a sibling game could not provide a scripted seat.

## Decision

- `core.engine.FreeText(max_words, max_chars)` is a frozen marker. A game returns `[FreeText(...)]`, as the only entry, from `legal_actions` when any string is the move. `is_free_text(legal_actions)` is the one check every adapter uses. The constraints are advisory; `apply_action` stays the only authority and raises `IllegalActionError` as for any action.
- `OpenRouterBackend` sends `{"type": "string"}` (with `maxLength`) instead of an `enum`, describes the constraints in the user message, and appends a short free-text clause to the system prompt. Enumerated games send exactly what they sent before.
- `HumanCLIController` accepts any non-empty line and re-prompts on an empty one. The CLI's chat matcher treats any line as the action, except a line carrying the existing `chat:` prefix.
- The MCP server reports a free-text request from `list_legal_actions` as `{"free_text": "<constraints>"}` and `submit_action` takes `int | str`.
- `cli.BOT_REGISTRY` maps `bot:<name>` to a zero-argument `SeatController` factory, beside `GAME_REGISTRY`. `bot:random` stays built in.
- `agf play` gains repeatable `--config KEY=VALUE` (value parsed as JSON, else string) passed to `initial_state`. It had no way to pass config before.
- `examples/secretnumber` is a second throwaway reference game that exercises a free-text move and a hidden value (see ADR-0011), registered as `secretnumber`.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Carry the text in `SeatDecision.banter` | Banter is optional, unrecorded and not part of state or validation. |
| A new `ActionSpace` type with several kinds (int range, text, structured) | More machinery than one real use justifies; `FreeText` can grow fields or siblings later without breaking this. |
| Each game ships its own LLM and human adapters | The drift this framework exists to avoid. |
| Entry-point plugin system for games and bots | A registry dict already works for one sibling; revisit when there are several. |

## Consequences

Any game can have a text move with its LLM, human, CLI-chat and MCP paths working unchanged. `RandomBotController` still cannot play a free-text turn (it would return the marker), so a game needs its own bot. `FreeText` is only recognised as the sole entry; mixing it with other actions is unsupported. The registries are module-level dicts mutated by sibling packages, which is a convention rather than a published API.
