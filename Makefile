.DEFAULT_GOAL := help

.PHONY: help install lint typecheck test-unit test-integration test-e2e test all

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install the package + dev dependencies
	uv sync --all-extras --dev

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
