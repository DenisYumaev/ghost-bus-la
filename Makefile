# Day-to-day commands. `make help` lists them.
# Targets for the local stack (up), dbt, backfill, and
# resume-metrics arrive with the PRs that need them. There is deliberately
# never an apply target (CLAUDE.md hard rule 8).

.DEFAULT_GOAL := help
.PHONY: help install test lint fmt hooks tf-test plan-bootstrap plan selftest-s3 deploy-ingest gtfs-versions gtfs-load compact decode dbt-sync dbt test-integration migrate publish openapi web-check web-dev sql-drill sql-check sql-shell

help:  ## List the targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

install:  ## Install locked dev dependencies and the git hooks
	uv sync --all-packages --locked
	uv run pre-commit install

test:  ## Run all offline tests with coverage
	uv run pytest --cov --cov-report=term-missing

TEST_DATABASE_URL := postgresql+psycopg://ghostbus:ghostbus-test@127.0.0.1:54329/ghostbus_test

test-integration:  ## Start Postgres in Docker (compose.test.yml), run the integration tests, stop it
	trap 'docker compose -f compose.test.yml down' EXIT; \
	  docker compose -f compose.test.yml up -d --wait && \
	  GHOSTBUS_TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest -m integration

migrate:  ## Apply the Alembic migrations to $$GHOSTBUS_DATABASE_URL (never a URL on the command line)
	@test -n "$$GHOSTBUS_DATABASE_URL" || (echo "set GHOSTBUS_DATABASE_URL" && exit 2)
	uv run python -m ghostbus_api.migrations

publish:  ## Publish the serving tables from data/ghostbus.duckdb to $$GHOSTBUS_DATABASE_URL: make publish [ARGS=--force]
	@test -n "$$GHOSTBUS_DATABASE_URL" || (echo "set GHOSTBUS_DATABASE_URL" && exit 2)
	uv run python -m ghostbus_publish $(ARGS)

openapi:  ## Regenerate the committed OpenAPI document and the web app's types from it
	uv run python -m ghostbus_api.openapi --write services/api/openapi.json
	cd web && npm run -s gen:api

web-check:  ## Web app: install, generated types current, lint, types, format, tests (as CI runs them)
	cd web && npm ci --no-audit --no-fund && npm run -s gen:api && git diff --exit-code lib/api/schema.ts \
	  && npm run -s lint && npm run -s typecheck && npm run -s format:check && npm test \
	  && npm run -s build

web-dev:  ## Run the web app locally against $$GHOSTBUS_API_URL
	cd web && npm run dev

lint:  ## Lint, format check, type check, fixture sizes
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy packages/ghostbus_core/src services/ingest/src services/api/src services/publish/src pipeline/decode/src scripts tests packages/ghostbus_core/tests services/ingest/tests services/api/tests services/publish/tests pipeline/decode/tests
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

gtfs-versions:  ## Preview which schedule version is in force (read-only; make gtfs-load writes it)
	uv run python -m ghostbus_decode.gtfs_versions --bucket "$$(terraform -chdir=infra output -raw data_bucket_name)" --dry-run

gtfs-load:  ## Rebuild dim_schedule_version and extract every new GTFS version's tables to derived/
	uv run python -m ghostbus_decode.gtfs_tables --bucket "$$(terraform -chdir=infra output -raw data_bucket_name)"

compact:  ## Compact one closed UTC day of snapshots into derived/compacted/: make compact DAY=YYYY-MM-DD
	@test -n "$(DAY)" || (echo "usage: make compact DAY=YYYY-MM-DD" && exit 2)
	uv run python -m ghostbus_decode.compact --bucket "$$(terraform -chdir=infra output -raw data_bucket_name)" --day $(DAY)

decode:  ## Decode one compacted UTC day into typed tables in derived/decoded/: make decode DAY=YYYY-MM-DD
	@test -n "$(DAY)" || (echo "usage: make decode DAY=YYYY-MM-DD" && exit 2)
	uv run python -m ghostbus_decode.decode --bucket "$$(terraform -chdir=infra output -raw data_bucket_name)" --day $(DAY)

dbt-sync:  ## Copy marker-listed derived data for service dates START..END into data/: make dbt-sync START= END=
	@test -n "$(START)" || (echo "usage: make dbt-sync START=YYYY-MM-DD END=YYYY-MM-DD" && exit 2)
	@test -n "$(END)" || (echo "usage: make dbt-sync START=YYYY-MM-DD END=YYYY-MM-DD" && exit 2)
	uv run python -m ghostbus_decode.sync --bucket "$$(terraform -chdir=infra output -raw data_bucket_name)" --start $(START) --end $(END)

dbt:  ## Build and test every dbt model over data/ (run dbt-sync first)
	uv run dbt build --project-dir pipeline/dbt --profiles-dir pipeline/dbt

sql-drill:  ## SQL practice: list problems, or start one (make sql-drill P=03)
	@if [ -n "$(P)" ]; then uv run python scripts/sql_drill.py start $(P); else uv run python scripts/sql_drill.py list; fi

sql-check:  ## Check your SQL practice attempt: make sql-check P=03
	@test -n "$(P)" || (echo "usage: make sql-check P=03" && exit 2)
	@uv run python scripts/sql_drill.py check $(P)

sql-shell:  ## Open the duckdb shell on the synthetic practice tables
	@uv run python scripts/sql_drill.py build >/dev/null && duckdb data/sql-practice.duckdb
