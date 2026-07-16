import subprocess
import sys
from pathlib import Path


def _run_new_product(tmp_path: Path, product_name: str, *provider_args: str) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "new_product.py"
    output_dir = tmp_path / product_name
    command = [
        sys.executable,
        str(script_path),
        product_name,
        "--output-dir",
        str(output_dir),
        *provider_args,
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return output_dir


def test_new_product_google_scaffold_exports_profile_env_vars(tmp_path):
    output_dir = _run_new_product(tmp_path, "river-farm")
    generated_makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    generated_readme = (output_dir / "README.md").read_text(encoding="utf-8")
    generated_operator_doc = (output_dir / "docs" / "operator.md").read_text(
        encoding="utf-8"
    )

    assert (
        "export CODA_CORPUS_CONFIG CODA_CORPUS_OUT_DIR CODA_DOC_IDS"
        not in generated_makefile
    ), "Google Sheets scaffold should not export Coda-specific vars"
    assert (
        '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}"'
        in generated_makefile
    )
    assert (
        "`make profile-preflight` and `make profile-drive-folder` read "
        "`COHORT_CORPUS_CONFIG` and `DRIVE_FOLDER_ID` from `.env`."
    ) in generated_readme
    assert (
        "generated Makefile. Optionally set `DRIVE_FOLDER_OUT` and "
        "`COHORT_CORPUS_OUT_DIR`"
    ) in generated_operator_doc
    assert (output_dir / "config" / "cohort_corpus.json").exists()
    assert not (output_dir / "config" / "cohort_corpus.local.json").exists()


def test_new_product_coda_scaffold_writes_coda_config_and_docs(tmp_path):
    output_dir = _run_new_product(tmp_path, "market-ledger", "--coda")
    generated_makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    generated_readme = (output_dir / "README.md").read_text(encoding="utf-8")
    generated_operator_doc = (output_dir / "docs" / "operator.md").read_text(
        encoding="utf-8"
    )

    assert (
        "export CODA_CORPUS_CONFIG CODA_CORPUS_OUT_DIR CODA_DOC_IDS"
        in generated_makefile
    )
    assert (
        "`make profile-coda-corpus` reads `CODA_CORPUS_CONFIG` and `CODA_DOC_IDS` from `.env`."
    ) in generated_readme
    assert (
        "set `CODA_CORPUS_CONFIG` and `CODA_DOC_IDS` in `.env`, then run `make profile-coda-corpus`."
    ) in generated_operator_doc
    assert (output_dir / "config" / "coda_corpus.json").exists()
    assert not (output_dir / "config" / "coda_corpus.local.json").exists()
    assert (output_dir / "config" / "coda_live.local.json").exists()


def test_new_product_does_not_commit_into_existing_repo(tmp_path):
    """Scaffolding into an existing git repo must not auto-commit."""
    product_name = "existing-repo"
    output_dir = tmp_path / product_name
    output_dir.mkdir()

    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=str(output_dir),
        check=True,
        capture_output=True,
    )
    baseline_file = output_dir / "baseline.txt"
    baseline_file.write_text("baseline content\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "baseline.txt"],
        cwd=str(output_dir),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(output_dir),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@test.com",
            "commit",
            "-m",
            "baseline",
        ],
        check=True,
        capture_output=True,
    )

    _run_new_product(tmp_path, product_name)

    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "baseline" in result.stdout, (
        f"Expected 'baseline' commit to remain latest, got: {result.stdout}"
    )


def test_scaffold_copies_run_import_sh(tmp_path):
    output_dir = _run_new_product(tmp_path, "run-import-test")
    run_import = output_dir / "scripts" / "run_import.sh"
    assert run_import.exists(), f"Expected {run_import} to exist after scaffold"


def test_check_env_regression_no_bashism(tmp_path):
    """Generated Makefile must not contain bash-specific indirect expansion."""
    output_dir = _run_new_product(tmp_path, "no-bashism")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    assert "${!var:-}" not in makefile, (
        "check-env target uses bash-specific ${!var:-} syntax; "
        "use POSIX-compatible printenv instead"
    )


def test_check_env_works_with_posix_sh(tmp_path):
    """make check-env must pass/fail correctly for Google Sheets under /bin/sh (dash)."""
    output_dir = _run_new_product(tmp_path, "posix-check-env")
    env_file = output_dir / ".env"
    env_file.write_text(
        "WORKBENCH=/tmp\n"
        "DRIVE_FOLDER_ID=test-folder\n"
        "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=test@test.com\n"
    )

    result = subprocess.run(
        ["make", "-C", str(output_dir), "check-env"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check-env failed with all vars set:\n{result.stderr}{result.stdout}"
    )

    env_file.write_text(
        "WORKBENCH=/tmp\n"
        "DRIVE_FOLDER_ID=\n"
        "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=test@test.com\n"
    )
    result = subprocess.run(
        ["make", "-C", str(output_dir), "check-env"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "DRIVE_FOLDER_ID" in result.stderr


def test_check_env_coda_works_with_posix_sh(tmp_path):
    """make check-env must pass/fail correctly for Coda under /bin/sh (dash)."""
    output_dir = _run_new_product(tmp_path, "coda-check-env", "--coda")
    env_file = output_dir / ".env"
    env_file.write_text("WORKBENCH=/tmp\nCODA_API_TOKEN=test-token\n")

    result = subprocess.run(
        ["make", "-C", str(output_dir), "check-env"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check-env failed with all Coda vars set:\n{result.stderr}{result.stdout}"
    )

    env_file.write_text("WORKBENCH=/tmp\nCODA_API_TOKEN=\n")
    result = subprocess.run(
        ["make", "-C", str(output_dir), "check-env"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "CODA_API_TOKEN" in result.stderr


def test_generated_makefile_has_generate_pipeline_manifest_target(tmp_path):
    output_dir = _run_new_product(tmp_path, "pipeline-test")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    assert "generate-pipeline-manifest:" in makefile, (
        "Missing generate-pipeline-manifest target in scaffolded Makefile"
    )


def test_generate_all_includes_pipeline_manifest(tmp_path):
    output_dir = _run_new_product(tmp_path, "genall-test")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    genall_line = makefile.split("generate-all:")[1].split("\n")[0]
    assert "generate-pipeline-manifest" in genall_line, (
        "generate-all target does not include generate-pipeline-manifest"
    )


def test_cohort_corpus_config_has_documentation_for_tab_overrides(tmp_path):
    """Generated cohort_corpus.json must document tab_selection_overrides schema."""
    output_dir = _run_new_product(tmp_path, "doc-tab-override")
    config_path = output_dir / "config" / "cohort_corpus.json"
    import json

    with config_path.open() as fh:
        doc = json.load(fh)

    docs = doc.get("_documentation", {})
    assert "tab_selection_overrides" in docs, (
        f"Missing tab_selection_overrides in _documentation. Keys present: {list(docs.keys())}"
    )
    assert "common_mistakes" in docs["tab_selection_overrides"]
    assert "include" in docs["tab_selection_overrides"]["common_mistakes"]


def test_generated_makefile_has_import_preflight_and_apply(tmp_path):
    output_dir = _run_new_product(tmp_path, "import-test")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    assert "import-preflight:" in makefile
    assert "import-apply:" in makefile


def test_generated_makefile_has_pull_preflight_and_apply(tmp_path):
    output_dir = _run_new_product(tmp_path, "pull-test")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    assert "pull-preflight:" in makefile
    assert "pull-apply:" in makefile


def test_generate_view_manifest_appears_exactly_once(tmp_path):
    """Regression test for the duplicate generate-view-manifest bug."""
    output_dir = _run_new_product(tmp_path, "manifest-once")
    makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    count = makefile.count("generate-view-manifest:")
    assert count == 1, (
        f"Expected exactly 1 'generate-view-manifest:' target, found {count}"
    )
