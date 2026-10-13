# ADR-0011: Connector output is viewer-scoped by default

- Status: Accepted
- Date: 2026-10-14
- Deciders: Jian (requested by Wavelength planning, `leejianrong/wavelength` ADR-0003)

## Context

ADR-0003 says hidden information is enforced once, in `observation_for`. It was not true of the connectors: `agf play --json` printed `match.serialize()` on every turn and in the result, and the MCP server returned it from `get_state_dump` and from every successful `submit_action`. `serialize` must round-trip the whole state, so for a game with a hidden value (a Wavelength target, poker hole cards) both leaked it to whoever was reading. The MCP server also let any client ask `get_observation` for any seat, and the CLI's renderer was fed the *mover's* observation, so a human would be shown an LLM opponent's private view.

## Decision

- `agf play` picks a **viewer**: the first human seat, or none when there is no human (a pure spectator has nobody to hide anything from) or when `--omniscient` is passed. `--json` turn and result `state` is `observation_for(viewer)` when there is a viewer and the full `serialize()` dump otherwise. The renderer is fed the viewer's observation, and the mover's only when there is no viewer.
- `build_server(match, *, omniscient=False, bound_seat=None)`: `get_state_dump` and `submit_action` return the caller's own `observation_for` unless `omniscient=True`, which restores the full dump. `bound_seat` pins the server to one seat: `player` becomes optional and means that seat, and naming another seat is a tool error.
- `serialize`/`deserialize` are unchanged: they are the save format and are never a viewer format.
- The `python -m ...mcp.server` demo for Tic-Tac-Toe, which has no hidden information, runs `omniscient=True` and keeps its behaviour.

## Alternatives considered

| Option | Why not |
|--------|---------|
| A `redact(state, viewer)` method on `GameEngine` | A contract change every game must remember to implement; defaulting to `observation_for` is safe with no per-game work. |
| Keep full dumps and trust agents not to read them | The framework's value is enforced rules, not trusted ones. |
| Scope only the MCP server | `--json` is read by a human at the terminal and by scripts; same leak. |

## Consequences

A game with hidden information is safe through both connectors by default. Output for a Tic-Tac-Toe `--json` match with a human seat changes shape (it is now the human's observation rather than the raw state; all-AI matches and `--omniscient` are unchanged). Hot-seat play of a hidden-information game (several humans on one terminal) is not protected, since one viewer is picked. The viewer for a chat-enabled or human seat is trusted to be the person at the keyboard.
