-include .env
export

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(PYTHON) -m pip
MANAGE = $(PYTHON) manage.py
PYTEST = $(PYTHON) -m pytest
BLACK = $(VENV)/bin/black

.PHONY: install migrate run shell manage test check format pull-bundle snapshot-bundle import-preflight import-apply pull-preflight pull-apply chassis-gate

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

format:
	$(BLACK) .

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

chassis-gate:
	mkdir -p build/_out
	DB_ENGINE=sqlite $(MANAGE) migrate --noinput
	DB_ENGINE=sqlite $(PYTEST) connectors profiler/tests importer/tests examples/tests
	DB_ENGINE=sqlite $(MANAGE) profile_drive_folder --smoke
	DB_ENGINE=sqlite $(MANAGE) profile_tab --smoke
	DB_ENGINE=sqlite $(MANAGE) profile_coda_doc --smoke
	DB_ENGINE=sqlite $(MANAGE) profile_coda_table --smoke
	DB_ENGINE=sqlite $(MANAGE) scan_formula_patterns --config example_data/scan_formula_patterns.example.json --out build/_out/scan-formula-smoke.json --smoke
	DB_ENGINE=sqlite $(MANAGE) scan_coda_formula_columns --config example_data/scan_coda_formula_columns.example.json --out build/_out/scan-coda-smoke.json --smoke
	DB_ENGINE=sqlite $(MANAGE) pull_bundle --help >/dev/null
	DB_ENGINE=sqlite $(MANAGE) snapshot_bundle --help >/dev/null
	DB_ENGINE=sqlite $(MANAGE) import_reference_example example_data --validate-only --summary-json build/_out/validate-example.json
	DB_ENGINE=sqlite $(MANAGE) import_reference_example example_data --summary-json build/_out/apply-example.json
