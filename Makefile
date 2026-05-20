-include .env
export

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(PYTHON) -m pip
MANAGE = $(PYTHON) manage.py
PYTEST = $(PYTHON) -m pytest
BLACK = $(VENV)/bin/black

.PHONY: install migrate reset-migrations run shell manage test check doc-coverage format pull-bundle snapshot-bundle import-preflight import-apply load-data push-data pull-preflight pull-apply chassis-gate profile-coda-preflight profile-coda-corpus profile-coda-canvas profile-cohort-corpus validate-domain-context draft-domain-context extract-workbook-codes orient manifest-lint health-smoke new-product publish validate-contract diff-generated generate-models generate-admin-light generate-admin generate-import generate-view-manifest generate-pipeline-manifest generate-all post-generate check-generated snapshot-codegen check-snapshots drift-check docker-build fly-launch fly-volume fly-secrets fly-deploy

install:
	$(PIP) install -e ".[dev]"

migrate:
	$(MANAGE) makemigrations
	$(MANAGE) migrate

reset-migrations:
	rm -f $(CORE)/migrations/*.py
	rm -rf $(CORE)/migrations/__pycache__
	$(MANAGE) makemigrations $(or $(APP_LABEL),core)

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
	wb validate contract --contract "$(CONTRACT)"

diff-generated:
	wb generate models --contract $(CONTRACT) --out $(OUT) --diff

drift-check:
	$(PYTHON) -m deployment.wb_cli drift check --baseline "$(CONTRACT)" --new "$(CONTRACT)"

SPACE ?= demo
ENV ?= preview

deploy:
	$(PYTHON) -m deployment.wb_cli --manifest deploy/spaces.yml deploy $(SPACE) --env $(ENV) --live

generate-models:
	wb generate models --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)

generate-admin-light:
	wb generate admin --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)

generate-admin:
	wb generate admin --contract $(CONTRACT) --manifest $(MANIFEST) --out $(OUT) $(if $(FORCE),--force)

generate-import:
	wb generate import --contract $(CONTRACT) --out $(OUT) $(if $(FORCE),--force)

generate-view-manifest:
	wb generate manifest --contract $(CONTRACT) $(if $(FORCE),--force)

generate-pipeline-manifest:
	$(MANAGE) generate_pipeline_manifest --contract $(CONTRACT) --corpus-config $${CORPUS_CONFIG:?CORPUS_CONFIG required} --out $${PIPELINE_MANIFEST_OUT:-build/pipeline_manifest.yaml} $(if $(FORCE),--force)

generate-all: generate-models generate-view-manifest generate-admin generate-import generate-pipeline-manifest
	@echo "All code generation complete."

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

load-data:
	RUNNER_MODE=local MANAGE_PY="$(MANAGE)" IMPORT_DATA_DIR="$${IMPORT_DATA_DIR:-example_data}" IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" scripts/run_import.sh import_apply

push-data:
	@gzip -c backend/db.sqlite3 | flyctl ssh console -a $${FLY_APP:-product-production} -C "gunzip > /data/db.sqlite3" 2>/dev/null || echo "push-data: set FLY_APP and ensure flyctl is authenticated"

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

validate-domain-context:
	@test -n "$(DOMAIN_CONTEXT)" || (echo "Usage: make validate-domain-context DOMAIN_CONTEXT=path/to/domain_context.yaml"; exit 1)
	DB_ENGINE=sqlite $(MANAGE) validate_domain_context --config "$(DOMAIN_CONTEXT)"

draft-domain-context:
	@test -n "$(DRIVE_TREE)" || (echo "Usage: make draft-domain-context DRIVE_TREE=path/to/drive_tree.json"; exit 1)
	DB_ENGINE=sqlite $(MANAGE) draft_domain_context --drive-tree "$(DRIVE_TREE)" $(if $(OUT),--out "$(OUT)")

extract-workbook-codes:
	@test -n "$(DRIVE_TREE)" || (echo "Usage: make extract-workbook-codes DRIVE_TREE=path/to/drive_tree.json"; exit 1)
	@test -n "$(COHORT_CORPUS_CONFIG)" || (echo "Usage: make extract-workbook-codes COHORT_CORPUS_CONFIG=path/to/cohort_corpus.json"; exit 1)
	DB_ENGINE=sqlite $(MANAGE) extract_workbook_codes --drive-tree "$(DRIVE_TREE)" --config "$(COHORT_CORPUS_CONFIG)" --update-config

orient: validate-domain-context draft-domain-context extract-workbook-codes profile-drive-folder

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
	# Build temp domain app from scaffolded contract so import validation can run
	mkdir -p build/_out/domain
	touch build/_out/domain/__init__.py
	printf 'import os, sys\nsys.path.insert(0, os.path.dirname(__file__))\nfrom migration_workbench.settings import *\nINSTALLED_APPS = list(INSTALLED_APPS) + ["domain"]\n' > build/_out/chassis_gate_settings.py
	DB_ENGINE=sqlite DJANGO_SETTINGS_MODULE=chassis_gate_settings PYTHONPATH=build/_out:$$PYTHONPATH $(MANAGE) generate_models --contract build/_out/schema-contract-smoke.yaml --out build/_out/domain/models.py --force
	DB_ENGINE=sqlite DJANGO_SETTINGS_MODULE=chassis_gate_settings PYTHONPATH=build/_out:$$PYTHONPATH $(MANAGE) migrate domain --run-syncdb
	DB_ENGINE=sqlite $(MANAGE) scaffold_view_manifest --structure example_data/scaffold_view_manifest_structure.example.json --out build/_out/view-manifest-smoke.yaml --summary-json build/_out/view-manifest-smoke.json
	DB_ENGINE=sqlite $(MANAGE) generate_admin --contract build/_out/schema-contract-smoke.yaml --manifest build/_out/view-manifest-smoke.yaml --out /dev/null --force
	DB_ENGINE=sqlite $(MANAGE) generate_import --contract build/_out/schema-contract-smoke.yaml --out build/_out/import_data.py --force
	DB_ENGINE=sqlite DJANGO_SETTINGS_MODULE=chassis_gate_settings PYTHONPATH=build/_out:$$PYTHONPATH $(MANAGE) shell -c "from import_data import Command; from importer.base import BaseImportCommand; assert issubclass(Command, BaseImportCommand); print('import validation: OK')"
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

doc-coverage:  ## Check PEP 257 docstring coverage (threshold: 80%)
	$(VENV)/bin/interrogate -v --fail-under 80 connectors profiler importer workbook deployment

# ---------------------------------------------------------------------------
# Docker / Fly.io deployment
# ---------------------------------------------------------------------------

DOCKER_IMAGE ?= product
FLY_APP ?= product-production

docker-build:
	docker build -t $(DOCKER_IMAGE) .

fly-launch:
	flyctl launch --name $(FLY_APP) --region ewr --no-deploy --copy-config || true

fly-volume:
	flyctl volumes create data --app $(FLY_APP) --region ewr --size 1 --yes

fly-secrets:
	flyctl secrets set DJANGO_SECRET_KEY=$$(python3 -c "import secrets; print(secrets.token_urlsafe(50))") DJANGO_ALLOWED_HOSTS=$(FLY_APP).fly.dev DJANGO_DEBUG=0

fly-deploy: docker-build
	flyctl deploy --app $(FLY_APP)

deploy: fly-launch fly-volume fly-secrets fly-deploy
