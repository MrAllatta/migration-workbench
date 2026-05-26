"""Shared Makefile target definitions used by the product scaffold.

Each builder function returns a complete Makefile target block (string)
parameterized by a MakeContext dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class MakeContext:
    """Paths and variable names for Makefile target templates."""

    manage: str = "$(MANAGE)"
    contract: str = "$(CONTRACT)"
    core: str = "$(CORE)"
    bundle_out: str = "$(BUNDLE_OUT)"
    view_manifest: str = "$(VIEW_MANIFEST)"
    python: str = "$(PYTHON)"
    product_kebab: str = "product"

    def with_overrides(
        self,
        *,
        manage: str | None = None,
        contract: str | None = None,
        core: str | None = None,
        bundle_out: str | None = None,
        view_manifest: str | None = None,
        python: str | None = None,
        product_kebab: str | None = None,
    ) -> MakeContext:
        """Return a new MakeContext with only the given fields replaced."""
        kwargs = {
            k: v
            for k, v in {
                "manage": manage,
                "contract": contract,
                "core": core,
                "bundle_out": bundle_out,
                "view_manifest": view_manifest,
                "python": python,
                "product_kebab": product_kebab,
            }.items()
            if v is not None
        }
        return replace(self, **kwargs)


def phonies(ctx: MakeContext) -> list[str]:
    """Return all shared phony target names."""
    return [
        "generate-models",
        "generate-admin",
        "generate-import",
        "generate",
        "generate-view-manifest",
        "generate-pipeline-manifest",
        "generate-all",
        "diff-generated",
        "generate-admin-light",
        "post-generate",
        "check-generated",
        "snapshot-codegen",
        "check-snapshots",
        "drift-check",
        "pull-bundle",
        "load-data",
        "push-data",
        "import-preflight",
        "import-apply",
        "pull-preflight",
        "pull-apply",
        "generate-discovery-interview",
        "merge-discovery-notes",
        "profile-preflight",
        "profile-drive-folder",
        "profile-coda-corpus",
        "profile-cohort-corpus",
        "profile-cohort-corpus-phase1",
        "profile-cohort-corpus-phase2",
        "profile-cohort-corpus-phase3",
        "draft-domain-context",
        "validate-domain-context",
        "extract-workbook-codes",
        "orient",
        "docker-build",
        "fly-launch",
        "fly-volume",
        "fly-secrets",
        "fly-deploy",
        "deploy",
        "createsuperuser",
    ]


def _indent(text: str, level: int = 1) -> str:
    """Indent text with a tab for Makefile recipe lines."""
    return "\t" * level + text


def variables_block(ctx: MakeContext) -> str:
    """Return the Makefile variable assignment block (CONTRACT, CORE, etc.)."""
    return """\
CONTRACT = config/contract.yaml
CORE = backend/apps/core
BUNDLE_OUT = build/bundle
VIEW_MANIFEST = config/view-manifest.yaml

# Corpus profiling date stamp -- set to the date of your Phase 1 run for resume phases.
DATE_STAMP = $(shell date +%Y-%m-%d)
"""


def generate_models_block(ctx: MakeContext) -> str:
    """Return the generate-models Makefile target block."""
    return (
        "generate-models:\n"
        + _indent(
            f'wb generate models --contract "{ctx.contract}" '
            f'--out "{ctx.core}/models.py" --force'
        )
        + "\n"
    )


def generate_admin_block(ctx: MakeContext) -> str:
    """Return the generate-admin Makefile target block (with optional manifest)."""
    return (
        "generate-admin:\n"
        + _indent(
            '@if [ -f "$(VIEW_MANIFEST)" ]; then \\\n'
            'wb generate admin --contract "$(CONTRACT)" '
            '--manifest "$(VIEW_MANIFEST)" '
            '--out "$(CORE)/admin.py" --app-label core --force; \\\n'
            "else \\\n"
            'wb generate admin --contract "$(CONTRACT)" '
            '--out "$(CORE)/admin.py" --app-label core --force; \\\n'
            "fi"
        )
        + "\n"
    )


def generate_import_block(ctx: MakeContext) -> str:
    """Return the generate-import Makefile target block."""
    return (
        "generate-import:\n"
        + _indent(
            f'wb generate import --contract "{ctx.contract}" --app-label core --force'
        )
        + "\n"
    )


def generate_block(ctx: MakeContext) -> str:
    """Return the generate Makefile target (alias for models+admin+import)."""
    return "generate: generate-models generate-admin generate-import\n"


def generate_view_manifest_block(ctx: MakeContext) -> str:
    """Return the generate-view-manifest Makefile target block."""
    return (
        "generate-view-manifest:\n"
        + _indent(
            '@test -f "$(BUNDLE_OUT)/structure.json" '
            '|| (echo >&2 "structure.json not found at $(BUNDLE_OUT)/structure.json. '
            'Run make pull-bundle first."; exit 1)\n'
        )
        + _indent(
            f"wb generate manifest "
            f'--structure "{ctx.bundle_out}/structure.json" '
            f'--schema-contract "{ctx.contract}" '
            f'--out "{ctx.view_manifest}" '
            f"--summary-json build/view-manifest-summary.json"
        )
        + "\n"
    )


def generate_pipeline_manifest_block(ctx: MakeContext) -> str:
    """Return the generate-pipeline-manifest Makefile target block."""
    return (
        "generate-pipeline-manifest:\n"
        + _indent(
            '$(MANAGE) generate_pipeline_manifest '
            '--contract "$(CONTRACT)" '
            "--corpus-config $${CORPUS_CONFIG:?CORPUS_CONFIG required} "
            "--out $${PIPELINE_MANIFEST_OUT:-build/pipeline_manifest.yaml}"
        )
        + "\n"
    )


def generate_all_block(ctx: MakeContext) -> str:
    """Return the generate-all Makefile target block (runs every generator)."""
    return (
        "generate-all: generate-models generate-view-manifest generate-admin "
        "generate-import generate-pipeline-manifest\n"
        + _indent(
            '@echo "All code generation complete. '
            "Run 'make check-generated' to verify.\""
        )
        + "\n"
    )


def codegen_tooling_block(ctx: MakeContext) -> str:
    """Return Makefile targets for diff, snapshot, drift-check, and admin-light."""
    return (
        "diff-generated:\n"
        + _indent(
            f'wb generate models --contract "{ctx.contract}" '
            f'--out "{ctx.core}/models.py" --diff'
        )
        + "\n\n"
        + "generate-admin-light:\n"
        + _indent(
            f'wb generate admin --contract "{ctx.contract}" '
            f'--out "{ctx.core}/admin.py" --app-label core --force'
        )
        + "\n\n"
        + "post-generate:\n"
        + _indent(
            "@test -f scripts/post-generate.sh && bash scripts/post-generate.sh "
            '|| echo "No scripts/post-generate.sh found"'
        )
        + "\n\n"
        + "check-generated:\n"
        + _indent(
            f"""{ctx.python} -c "from {ctx.core.replace("/", ".")}.models import *; print('import OK')"""
        )
        + "\n"
        + _indent("$(MANAGE) check")
        + "\n\n"
        + "snapshot-codegen:\n"
        + _indent(
            f'wb generate models --contract "{ctx.contract}" '
            f"--out build/snapshots/models.py --force"
        )
        + "\n"
        + _indent(
            f'wb generate admin --contract "{ctx.contract}" '
            f"--out build/snapshots/admin.py --force"
        )
        + "\n"
        + _indent(
            f'wb generate import --contract "{ctx.contract}" '
            f"--out build/snapshots/imports.py --force"
        )
        + "\n\n"
        + "check-snapshots:\n"
        + _indent(
            f"""{ctx.python} -c "from {ctx.core.replace("/", ".")}.models import *; print('OK')"""
        )
        + "\n"
        + _indent("$(MANAGE) check")
        + "\n\n"
        + "drift-check:\n"
        + _indent(
            f"{ctx.python} -m deployment.wb_cli drift check "
            f'--baseline "{ctx.contract}" --new "{ctx.contract}"'
        )
        + "\n"
    )


def import_blocks(ctx: MakeContext) -> str:
    """Return Makefile targets for bundle pull, import, and discovery."""
    return (
        "pull-bundle:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG required}" '
            'BUNDLE_OUTPUT_DIR="$(BUNDLE_OUT)" INCLUDE_STRUCTURE=true '
            "scripts/run_import.sh pull_bundle"
        )
        + "\n\n"
        + "load-data:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'IMPORT_DATA_DIR="$${IMPORT_DATA_DIR:-example_data}" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh import_apply"
        )
        + "\n\n"
        + "push-data:\n"
        + _indent(
            "@gzip -c backend/db.sqlite3 | flyctl ssh console -a "
            f"$${{FLY_APP:-{ctx.product_kebab}-production}} -C "
            '"gunzip > /data/db.sqlite3" 2>/dev/null '
            '|| echo "push-data: set FLY_APP and ensure flyctl is authenticated"'
        )
        + "\n\n"
        + "import-preflight:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'IMPORT_DATA_DIR="$${IMPORT_DATA_DIR:-example_data}" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh import_preflight"
        )
        + "\n\n"
        + "import-apply:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'IMPORT_DATA_DIR="$${IMPORT_DATA_DIR:-example_data}" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh import_apply"
        )
        + "\n\n"
        + "pull-preflight:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG required}" '
            'BUNDLE_OUTPUT_DIR="$(BUNDLE_OUT)" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh pull_preflight"
        )
        + "\n\n"
        + "pull-apply:\n"
        + _indent(
            'RUNNER_MODE=local MANAGE_PY="$(MANAGE)" '
            'SOURCE_CONFIG="$${SOURCE_CONFIG:?SOURCE_CONFIG required}" '
            'BUNDLE_OUTPUT_DIR="$(BUNDLE_OUT)" '
            'IMPORT_COMMAND="$${IMPORT_COMMAND:-import_reference_example}" '
            'IMPORT_SUMMARY_JSON="$${IMPORT_SUMMARY_JSON:-}" '
            "scripts/run_import.sh pull_apply"
        )
        + "\n\n"
        + "generate-discovery-interview:\n"
        + _indent(
            '@test -f "$(VIEW_MANIFEST)" || (echo >&2 '
            '"View manifest not found at $(VIEW_MANIFEST). '
            'Run make generate-view-manifest first."; exit 1)'
        )
        + "\n"
        + _indent(
            "$(MANAGE) generate_discovery_interview "
            '--manifest "$(VIEW_MANIFEST)" '
            "--out build/discovery-interview.md"
        )
        + "\n\n"
        + "merge-discovery-notes:\n"
        + _indent(
            '@test -f "$(VIEW_MANIFEST)" || (echo >&2 '
            '"View manifest not found at $(VIEW_MANIFEST). '
            'Run make generate-view-manifest first."; exit 1)'
        )
        + "\n"
        + _indent(
            "@test -f build/discovery-interview.md || (echo >&2 "
            '"Discovery interview not found at build/discovery-interview.md. '
            'Run make generate-discovery-interview first."; exit 1)'
        )
        + "\n"
        + _indent(
            "$(MANAGE) merge_discovery_notes "
            '--manifest "$(VIEW_MANIFEST)" '
            "--interview build/discovery-interview.md "
            '--out "$(VIEW_MANIFEST)" '
            "--summary-out build/discovery-summary.md"
        )
        + "\n"
    )


def profile_blocks(ctx: MakeContext) -> str:
    """Return Makefile targets for profiler commands (preflight, drive-folder, corpus phases)."""
    return (
        "profile-preflight:\n"
        + _indent(
            "DB_ENGINE=sqlite $(MANAGE) profile_preflight "
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG}"'
        )
        + "\n\n"
        + "# Expected runtime: 2-3 minutes for folders with 20+ spreadsheets.\n"
        + "profile-drive-folder:\n"
        + _indent(
            "DB_ENGINE=sqlite $(MANAGE) profile_drive_folder "
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG}" '
            '--out "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}"'
        )
        + "\n\n"
        + "profile-coda-corpus:\n"
        + _indent(
            "DB_ENGINE=sqlite $(MANAGE) profile_coda_corpus "
            '--config "$${CODA_CORPUS_CONFIG:?CODA_CORPUS_CONFIG required}" '
            '--out-dir "$${CODA_CORPUS_OUT_DIR:-build/coda_corpus}"'
        )
        + "\n\n"
        + "profile-cohort-corpus:\n"
        + _indent(
            "DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus "
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" '
            '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}" '
            '--date-stamp "$(DATE_STAMP)"'
        )
        + "\n\n"
        + "# Phase 1: discovery + tab selection only (no deep API calls). "
        "Inspect tab_selection_<date>.json, then configure heuristics.\n"
        + "profile-cohort-corpus-phase1:\n"
        + _indent(
            "DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus "
            '--folder "$${DRIVE_FOLDER_ID:?DRIVE_FOLDER_ID required}" '
            '--config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" '
            '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}" '
            '--date-stamp "$(DATE_STAMP)" --stop-before-deep'
        )
        + "\n\n"
        + "# Phase 2: re-run heuristics from broad coverage (no API calls). "
        "Iterate on cohort_corpus.json, then re-run.\n"
        + "profile-cohort-corpus-phase2:\n"
        + _indent(
            "DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus "
            '--config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" '
            '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}" '
            '--date-stamp "$(DATE_STAMP)" --resume-from-broad --stop-before-deep'
        )
        + "\n\n"
        + "# Phase 3: deep profile from hand-edited tab_selection_<date>.json. "
        "Run after heuristics are final.\n"
        + "# Available tab_score heuristics: tab_exclude_patterns (regex block list), "
        "expansion_formula_penalty, expansion_formula_threshold, plus token lists.\n"
        + "profile-cohort-corpus-phase3:\n"
        + _indent(
            "DB_ENGINE=sqlite $(MANAGE) profile_cohort_corpus "
            '--config "$${COHORT_CORPUS_CONFIG:?COHORT_CORPUS_CONFIG required}" '
            '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}" '
            '--date-stamp "$(DATE_STAMP)" --resume-from-tab-selection'
        )
        + "\n"
    )


def deploy_blocks(ctx: MakeContext) -> str:
    """Return Makefile targets for Docker build, Fly.io, and deployment."""
    return (
        "docker-build:\n"
        + _indent("docker build -t $(DOCKER_IMAGE) .")
        + "\n\n"
        + "fly-launch:\n"
        + _indent(
            "flyctl launch --name $(FLY_APP) "
            "--region ewr --no-deploy --copy-config || true"
        )
        + "\n\n"
        + "fly-volume:\n"
        + _indent(
            "flyctl volumes create data --app $(FLY_APP) --region ewr --size 1 --yes"
        )
        + "\n\n"
        + "fly-secrets:\n"
        + _indent(
            "flyctl secrets set DJANGO_SECRET_KEY=$$(python3 -c "
            '"import secrets; print(secrets.token_urlsafe(50))") '
            "DJANGO_ALLOWED_HOSTS=$(FLY_APP).fly.dev DJANGO_DEBUG=0"
        )
        + "\n\n"
        + "fly-deploy: docker-build\n"
        + _indent("flyctl deploy --app $(FLY_APP)")
        + "\n\n"
        + "deploy: fly-launch fly-volume fly-secrets fly-deploy\n"
    )


def createsuperuser_block(ctx: MakeContext) -> str:
    """Target for non-interactive superuser creation."""
    return (
        "createsuperuser:\n"
        + _indent(
            '@if [ -z "$(DJANGO_SUPERUSER_PASSWORD)" ]; then \\\n'
            "$(MANAGE) createsuperuser; \\\n"
            "else \\\n"
            "DJANGO_SUPERUSER_PASSWORD='$(DJANGO_SUPERUSER_PASSWORD)' \\\n"
            "$(MANAGE) createsuperuser --noinput "
            "--username '$(DJANGO_SUPERUSER_USERNAME)' "
            "--email '$(DJANGO_SUPERUSER_EMAIL)'; \\\n"
            "fi"
        )
        + "\n"
    )


def draft_domain_context_block(ctx: MakeContext) -> str:
    return (
        "draft-domain-context:\n"
        + _indent(
            '$(MANAGE) draft_domain_context '
            '--drive-tree "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}" '
            '--out config/domain_context.yaml'
        )
        + "\n\n"
    )


def validate_domain_context_block(ctx: MakeContext) -> str:
    return (
        "validate-domain-context:\n"
        + _indent('$(MANAGE) validate_domain_context --config config/domain_context.yaml')
        + "\n\n"
    )


def extract_workbook_codes_block(ctx: MakeContext) -> str:
    return (
        "extract-workbook-codes:\n"
        + _indent(
            '$(MANAGE) extract_workbook_codes '
            '--drive-tree "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}" '
            '--config config/cohort_corpus.json '
            '--update-config'
        )
        + "\n\n"
    )


def orient_block(ctx: MakeContext) -> str:
    return "orient: validate-domain-context profile-drive-folder extract-workbook-codes\n\n"


def full_targets_block(ctx: MakeContext) -> str:
    """Return all shared target blocks concatenated into one Makefile section."""
    parts = [
        variables_block(ctx),
        "\n",
        codegen_tooling_block(ctx),
        "\n",
        draft_domain_context_block(ctx),
        validate_domain_context_block(ctx),
        extract_workbook_codes_block(ctx),
        orient_block(ctx),
        generate_models_block(ctx),
        generate_admin_block(ctx),
        generate_import_block(ctx),
        generate_block(ctx),
        generate_view_manifest_block(ctx),
        generate_pipeline_manifest_block(ctx),
        generate_all_block(ctx),
        "\n",
        import_blocks(ctx),
        "\n",
        profile_blocks(ctx),
        "\n",
        deploy_blocks(ctx),
        "\n",
        createsuperuser_block(ctx),
    ]
    return "".join(parts)
