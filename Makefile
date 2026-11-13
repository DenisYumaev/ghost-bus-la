# Day-to-day commands. `make help` lists them.
# Targets for the local stack (up), dbt, backfill, and
# resume-metrics arrive with the PRs that need them. There is deliberately
# never an apply target (CLAUDE.md hard rule 8).

.DEFAULT_GOAL := help
.PHONY: help install test lint fmt hooks tf-test plan-bootstrap plan selftest-s3 deploy-ingest

help:  ## List the targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

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
	cd infra && terraform init -backend=false -input=false >/dev/null && terraform validate && terraform test

plan-bootstrap:  ## Plan the state bucket (read-only against AWS; apply is done by hand after review)
	cd infra/bootstrap && terraform init -input=false && terraform plan -out=bootstrap.tfplan

plan:  ## Plan the main configuration (needs infra/backend.hcl and infra/terraform.tfvars)
	cd infra && terraform init -input=false -backend-config=backend.hcl && terraform plan -out=main.tfplan

selftest-s3:  ## Prove conditional writes and the no-overwrite policy on the real bucket (selftest/ only)
	uv run python scripts/selftest_conditional_writes.py --bucket "$$(terraform -chdir=infra output -raw data_bucket_name)"

deploy-ingest:  ## Deploy ingest to the VM over SSM: make deploy-ingest SHA=<full git sha on main>
	@test -n "$(SHA)" || (echo "usage: make deploy-ingest SHA=<full git sha>" && exit 2)
	uv run python scripts/deploy_ingest.py $(SHA)
