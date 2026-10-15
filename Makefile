.DEFAULT_GOAL := help

# Model the demos use for every LLM seat. Override per run: make demo DEMO_MODEL=openai/gpt-4o-mini
DEMO_MODEL ?= deepseek/deepseek-v4.1-flash

.PHONY: help install lint typecheck test-unit test-integration test-e2e test all play demo demo-advised demo-ai-vs-ai

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install the package + dev dependencies
	uv sync --all-extras --dev

play: install ## Play tic-tac-toe: you (X) vs. a random bot (O)
	uv run agf play tictactoe --seat X=human --seat O=bot:random

demo: install ## Play tic-tac-toe vs. an unbeatable minimax O, narrated by an LLM you can also chat with -- needs OPENROUTER_API_KEY in .env
	@test -f .env || { echo "Missing .env -- copy .env.example to .env and set OPENROUTER_API_KEY first."; exit 1; }
	uv run --env-file .env agf play tictactoe --seat X=human \
		--seat O=algo:tictactoe-minimax:narrated-by=llm:openrouter/$(DEMO_MODEL)

demo-advised: install ## Play tic-tac-toe vs. an LLM O that decides for itself, advised by minimax's recommendation (can still lose) -- needs OPENROUTER_API_KEY in .env
	@test -f .env || { echo "Missing .env -- copy .env.example to .env and set OPENROUTER_API_KEY first."; exit 1; }
	uv run --env-file .env agf play tictactoe --seat X=human \
		--seat O=llm:openrouter/$(DEMO_MODEL):advised-by=algo:tictactoe-minimax

demo-ai-vs-ai: install ## Watch two LLMs play tic-tac-toe against each other, no human seat, trash-talking after every move -- needs OPENROUTER_API_KEY in .env
	@test -f .env || { echo "Missing .env -- copy .env.example to .env and set OPENROUTER_API_KEY first."; exit 1; }
	uv run --env-file .env agf play tictactoe \
		--seat X=llm:openrouter/$(DEMO_MODEL) \
		--seat O=llm:openrouter/$(DEMO_MODEL)

lint: ## Run ruff
	uv run ruff check .

typecheck: ## Run mypy
	uv run mypy src examples

test-unit: ## Run the no-infra unit test layer
	uv run pytest tests/unit -q

test-integration: ## Run the integration test layer (in-process / local subprocess only)
	uv run pytest tests/integration -q

test-e2e: ## Run end-to-end tests (drives the CLI / an MCP client)
	uv run pytest tests/e2e -q

test: test-unit test-integration test-e2e ## Run the full test suite

all: lint typecheck test ## Everything CI runs
