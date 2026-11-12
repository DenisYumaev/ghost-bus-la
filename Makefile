# Day-to-day commands. `make help` lists them.
# Targets for the local stack (up), the main terraform plan, dbt, backfill, and
# resume-metrics arrive with the PRs that need them. There is deliberately
# never an apply target (CLAUDE.md hard rule 8).

.DEFAULT_GOAL := help
.PHONY: help install test lint fmt hooks tf-test plan-bootstrap

help:  ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install:  ## Install locked dev dependencies and the git hooks
	uv sync --all-packages --locked
	uv run pre-commit install

test:  ## Run all offline tests with coverage
	uv run pytest --cov --cov-report=term-missing

lint:  ## Lint, format check, type check, fixture sizes
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy packages/ghostbus_core/src services/ingest/src scripts tests packages/ghostbus_core/tests services/ingest/tests
	uv run python scripts/check_fixture_size.py

fmt:  ## Auto-fix lint issues and format
	uv run ruff check --fix .
	uv run ruff format .

hooks:  ## Run every pre-commit hook on every file
	uv run pre-commit run --all-files

tf-test:  ## Terraform format check, validate, and offline tests (mock provider)
	terraform fmt -check -recursive infra
	cd infra/bootstrap && terraform init -backend=false -input=false >/dev/null && terraform validate && terraform test

plan-bootstrap:  ## Plan the state bucket (read-only against AWS; apply is done by hand after review)
	cd infra/bootstrap && terraform init -input=false && terraform plan -out=bootstrap.tfplan
