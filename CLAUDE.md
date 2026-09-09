# agent-game-framework

**Build status: V1, V2 (MCP connector), and V3 (LLM seat controller with
banter) complete.** `docs/PLAN.md`, `docs/SLICES.md`, and `docs/adr/*` are
the source of truth for *what* is being built and *why*. This file is the
source of truth for *how* to work in this repo day to day. If this file, the
docs, and the actual code ever disagree, trust the code — then fix whichever
doc is stale.

## What this is

An installable Python framework for playing turn-based/simultaneous-move games
(Tic-Tac-Toe now; Catan, Poker, Wavelength later, each in its own sibling repo)
with any mix of human and AI-controlled seats, including zero-human matches.
See `docs/PLAN.md` for the full problem/solution and `docs/adr/0001` through
`0008` for the architectural decisions already locked in.

## Current state

- V1 (core engine, CLI, human/bot seats, zero-required-human matches — epic
  `EPIC-180` on the `agent-games` Pandan board) is done, 7/7 cards.
- V2 (MCP connector, epic `EPIC-181`) is done: the stdio server
  (`get_observation`/`list_legal_actions`/`submit_action`/`get_state_dump`,
  `KAN-1281`), bot-filled seat assignment via `build_server(...,
  bot_seats=...)` (`KAN-1282`), and the full V2 test suite (`KAN-1283`) are
  all merged.
- V3 (LLM seat controller with banter via OpenRouter, epic `EPIC-182`) is
  done: `OpenRouterBackend` (`KAN-1284`), `Match`/CLI reject-and-reprompt-once
  plus `AgentTimeoutError` handling (`KAN-1285`), the `--seat
  llm:openrouter/<model>` CLI wiring (`KAN-1286`), and the full V3 e2e/test
  suite (`KAN-1287`) are all merged — see `docs/adr/0005`. This closes out
  R1's full 3-way human/AI/all-AI matrix and R3 (LLM banter).
- The command surface below (`make ...`) is real and gating — CI
  (`.github/workflows/ci.yml`) and the pre-push hook both run it on every
  push/PR.

## Toolchain

- Python 3.12+, managed with [`uv`](https://docs.astral.sh/uv/) (ADR-0002).
  Lockfile: `uv.lock`, created by `KAN-1274`.
- Lint/format: `ruff`. Types: `mypy`. Tests: `pytest`.
- Tests are split by cost, mirroring each slice's test plan in `SLICES.md`:
  `tests/unit` (no external calls, no subprocess), `tests/integration` (drives
  `Match`/the MCP server in-process or as a local subprocess — no real
  external infra needed for this project), `tests/e2e` (drives the CLI or an
  MCP client end-to-end).

## Commands

```
make help              # list all targets (this is what a bare `make` shows too)
make install           # uv sync --all-extras --dev
make lint              # ruff check .
make typecheck         # mypy src
make test-unit         # pytest tests/unit
make test-integration  # pytest tests/integration
make test-e2e          # pytest tests/e2e
make test              # all three test layers
make all               # everything CI runs: lint + typecheck + test
```

## Workflow

- **Branch per slice/card, off fresh `main`:** `git fetch origin && git switch -c <slug> origin/main`.
  PR-only — `main` is protected, no direct pushes. One kanban card is usually
  one PR; cite the ADR(s) the change rests on in the PR description.
- **Before pushing:** the pre-push hook mirrors CI's cheap jobs (lint +
  typecheck + `tests/unit`). Install once per clone:
  `git config core.hooksPath .githooks && chmod +x .githooks/pre-push`.
  Scoped exception when you've already verified the failure is unrelated:
  `git push --no-verify`.
- **New architectural decision?** If it's expensive to reverse or a future
  agent/session would otherwise re-litigate it, write an ADR in `docs/adr/`,
  numbered sequentially — see any existing one for the shape (Context /
  Decision / Alternatives considered / Consequences).
- **Testability seams already exist by design**, not something to add later:
  `GameEngine`, `SeatController`, and `GameAlgorithm` are typed Protocols
  (ADR-0003, ADR-0004, ADR-0005) specifically so tests can inject a fake
  implementation with zero external infra.
- **`OpenRouterBackend` (V3) and any live-API test must mock the HTTP call.**
  Never let CI make a real OpenRouter API call — it costs money and isn't
  deterministic. A real-key smoke test is a manual, local-only thing, not part
  of `make test` or CI.

## Secrets

`OPENROUTER_API_KEY` goes in `.env` (copy `.env.example`), which is
gitignored and must never be logged. No other secrets are expected in this
repo. If one ever leaks into git history, rotate it — assume history is
permanent.

## Docs

`docs/PLAN.md`, `docs/SLICES.md`, `docs/QUESTIONS.md`, `docs/adr/*`. No
published docs site yet — this repo has no external doc consumers so far
(ADR-0001 anticipates sibling game repos depending on the *package*, not
readers depending on hosted docs); revisit if that changes.
