-include .env
export

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(PYTHON) -m pip
MANAGE = $(PYTHON) manage.py
PYTEST = $(PYTHON) -m pytest
BLACK = $(VENV)/bin/black

.PHONY: install migrate run shell manage test check format pull-bundle snapshot-bundle import-preflight import-apply pull-preflight pull-apply chassis-gate profile-coda-preflight profile-coda-corpus profile-coda-canvas profile-cohort-corpus manifest-lint health-smoke new-product publish validate-contract diff-generated generate-admin generate-admin-light post-generate check-generated snapshot-codegen check-snapshots

install:
	$(PIP) install -e ".[dev]"

migrate:
	$(MANAGE) makemigrations
	$(MANAGE) migrate

run:
	$(MANAGE) runserver

shell:
	$(MANAGE) shell

manage:
	$(MANAGE) $(ARGS)

test:
	$(PYTEST)

check:
	$(MANAGE) check

manifest-lint:
	$(PYTHON) -m deployment.wb_cli --manifest deploy/spaces.yml --json manifest lint

health-smoke:
	$(MANAGE) shell -c "from django.test import Client; r = Client(HTTP_HOST='localhost').get('/healthz'); assert r.status_code == 200"

format:
	$(BLACK) .

CONTRACT ?= build/schema-contract.yaml
OUT ?= build/out.py

validate-contract:
	$(PYTHON) scripts/validate_contract.py "$(CONTRACT)"

diff-generated:
	$(MANAGE) generate_models --contract $(CONTRACT) --out $(OUT) --diff

generate-admin-light:
	$(MANAGE) generate_admin --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)

generate-admin:
	$(MANAGE) generate_admin --contract $(CONTRACT) --manifest $(MANIFEST) --out $(OUT) $(if $(FORCE),--force)

post-generate:
	@test -f scripts/post-generate.sh && bash scripts/post-generate.sh || echo "No scripts/post-generate.sh found"

check-generated:
	$(PYTHON) scripts/check_generated.py "$(MODELS_PY)" "$(ADMIN_PY)" "$(IMPORT_PY)"
	@echo "--- import check ---"
	$(PYTHON) -c "from $(or $(APP_LABEL),core).models import *; print('import OK')"
	@echo "--- django check ---"
	$(MANAGE) check

SNAPSHOT_DIR ?= build/codegen-snapshots

snapshot-codegen:
	$(PYTHON) scripts/snapshot_codegen.py --snapshot "$(CONTRACT)" --out-dir "$(SNAPSHOT_DIR)" --app-label "$(or $(APP_LABEL),core)"

check-snapshots:
	$(PYTHON) scripts/snapshot_codegen.py --check "$(CONTRACT)" --out-dir "$(SNAPSHOT_DIR)" --app-label "$(or $(APP_LABEL),core)"

pull-bundle:
	RUNNER_MODE=local MANAGE_PY="$(MANAGE)" SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG is required}" BUNDLE_OUTPUT_DIR="$${BUNDLE_OUTPUT_DIR:-bundle_out}" scripts/run_import.sh pull_bundle

snapshot-bundle:
	RUNNER_MODE=local MANAGE_PY="$(MANAGE)" SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG is required}" BUNDLE_OUTPUT_DIR="$${BUNDLE_OUTPUT_DIR:-bundle_out}" scripts/run_import.sh snapshot_bundle

import-preflight:
	RUNNER_MODE=local MANAGE_PY="$(MANAGE)" IMPORT_DATA_DIR="$${IMPORT_DATA_DIR:-example_data}" IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" scripts/run_import.sh import_preflight

import-apply:
	RUNNER_MODE=local MANAGE_PY="$(MANAGE)" IMPORT_DATA_DIR="$${IMPORT_DATA_DIR:-example_data}" IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" scripts/run_import.sh import_apply

pull-preflight:
	RUNNER_MODE=local MANAGE_PY="$(MANAGE)" SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG is required}" BUNDLE_OUTPUT_DIR="$${BUNDLE_OUTPUT_DIR:-bundle_out}" IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" scripts/run_import.sh pull_preflight

pull-apply:
	RUNNER_MODE=local MANAGE_PY="$(MANAGE)" SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG is required}" BUNDLE_OUTPUT_DIR="$${BUNDLE_OUTPUT_DIR:-bundle_out}" IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" scripts/run_import.sh pull_apply

profile-coda-preflight:
	DB_ENGINE=sqlite $(MANAGE) profile_coda_preflight --smoke

profile-coda-corpus:
	DB_ENGINE=sqlite $(MANAGE) profile_coda_corpus \
		--config "$${CODA_CORPUS_CONFIG:?CODA_CORPUS_CONFIG required}" \
		--out-dir "$${CODA_CORPUS_OUT_DIR:-build/coda_corpus}"

profile-cohort-corpus:
	DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus \
		--config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" \
		--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}"

profile-coda-canvas:
	DB_ENGINE=sqlite $(MANAGE) profile_coda_canvas --smoke

chassis-gate:
	mkdir -p build/_out
	DB_ENGINE=sqlite $(MANAGE) migrate --noinput
	DB_ENGINE=sqlite $(PYTEST) connectors profiler/tests importer/tests examples/tests deployment/tests workbook/tests
	DB_ENGINE=sqlite $(MAKE) manifest-lint
	DB_ENGINE=sqlite $(MAKE) health-smoke
	DB_ENGINE=sqlite $(MANAGE) profile_drive_folder --smoke
	DB_ENGINE=sqlite $(MANAGE) profile_tab --smoke
	DB_ENGINE=sqlite $(MANAGE) profile_coda_doc --smoke
	DB_ENGINE=sqlite $(MANAGE) profile_coda_table --smoke
	DB_ENGINE=sqlite $(MANAGE) scan_formula_patterns --config example_data/scan_formula_patterns.example.json --out build/_out/scan-formula-smoke.json --smoke
	DB_ENGINE=sqlite $(MANAGE) scan_coda_formula_columns --config example_data/scan_coda_formula_columns.example.json --out build/_out/scan-coda-smoke.json --smoke
	DB_ENGINE=sqlite $(MANAGE) profile_coda_preflight --smoke
	DB_ENGINE=sqlite $(MANAGE) profile_coda_canvas --smoke
	DB_ENGINE=sqlite $(MANAGE) profile_coda_corpus --config example_data/coda_corpus.example.json --out-dir build/_out/coda-corpus-smoke --smoke
	DB_ENGINE=sqlite $(MANAGE) pull_bundle --help >/dev/null
	DB_ENGINE=sqlite $(MANAGE) snapshot_bundle --help >/dev/null
	DB_ENGINE=sqlite $(MANAGE) scaffold_workbook_schema --bundle-config example_data/scaffold_workbook_bundle.example.json --table-profile example_data/scaffold_workbook_table_profile.example.json --out build/_out/schema-contract-smoke.yaml
	DB_ENGINE=sqlite $(MANAGE) generate_import --contract example_data/import_pipeline_contract.example.yaml --out build/_out/import-pipeline-smoke.py --force
	DB_ENGINE=sqlite $(MANAGE) generate_models --contract build/_out/schema-contract-smoke.yaml --out /dev/null --force
	DB_ENGINE=sqlite $(MANAGE) scaffold_view_manifest --structure example_data/scaffold_view_manifest_structure.example.json --out build/_out/view-manifest-smoke.yaml --summary-json build/_out/view-manifest-smoke.json
	DB_ENGINE=sqlite $(MANAGE) generate_admin --contract build/_out/schema-contract-smoke.yaml --manifest build/_out/view-manifest-smoke.yaml --out /dev/null --force
	DB_ENGINE=sqlite $(MANAGE) generate_import --contract build/_out/schema-contract-smoke.yaml --out build/_out/import_data.py --force
	$(PYTHON) -c "import sys; sys.path.insert(0, 'build/_out'); from import_data import Command; from importer.base import BaseImportCommand; assert issubclass(Command, BaseImportCommand)"
	DB_ENGINE=sqlite $(MANAGE) generate_discovery_interview --manifest build/_out/view-manifest-smoke.yaml --out build/_out/discovery-interview-smoke.md
	DB_ENGINE=sqlite $(MANAGE) merge_discovery_notes --manifest build/_out/view-manifest-smoke.yaml --interview example_data/discovery_interview.example.md --out build/_out/view-manifest-merged-smoke.yaml --summary-out build/_out/discovery-summary-smoke.md
	DB_ENGINE=sqlite $(MANAGE) import_reference_example example_data --validate-only --summary-json build/_out/validate-example.json
	DB_ENGINE=sqlite $(MANAGE) import_reference_example example_data --summary-json build/_out/apply-example.json

new-product:
	@test -n "$(PRODUCT)" || (echo "Usage: make new-product PRODUCT=name [PROVIDER=coda|google_sheets] [FORCE=1]"; exit 1)
	$(PYTHON) scripts/new_product.py $(PRODUCT) $(if $(PROVIDER),--$(subst _,-,$(PROVIDER))) $(if $(FORCE),--force)

publish:
	$(PYTHON) -m build
	$(PYTHON) -m twine upload dist/*
