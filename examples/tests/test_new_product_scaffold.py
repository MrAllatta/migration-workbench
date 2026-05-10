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

    assert "export COHORT_CORPUS_CONFIG COHORT_CORPUS_OUT_DIR DRIVE_FOLDER_OUT" in generated_makefile
    assert "export CODA_CORPUS_CONFIG CODA_CORPUS_OUT_DIR" in generated_makefile
    assert (
        '--out-dir "$${COHORT_CORPUS_OUT_DIR:-data/profile_snapshots/cohort_corpus}"'
        in generated_makefile
    )
    assert (
        "`make profile-preflight` and `make profile-drive-folder` read "
        "`COHORT_CORPUS_CONFIG` from `.env`."
    ) in generated_readme
    assert (
        "generated Makefile. Optionally set `DRIVE_FOLDER_OUT` and "
        "`COHORT_CORPUS_OUT_DIR`"
    ) in generated_operator_doc
    assert (output_dir / "config" / "cohort_corpus.local.json").exists()


def test_new_product_coda_scaffold_writes_coda_config_and_docs(tmp_path):
    output_dir = _run_new_product(tmp_path, "market-ledger", "--coda")
    generated_makefile = (output_dir / "Makefile").read_text(encoding="utf-8")
    generated_readme = (output_dir / "README.md").read_text(encoding="utf-8")
    generated_operator_doc = (output_dir / "docs" / "operator.md").read_text(
        encoding="utf-8"
    )

    assert "export CODA_CORPUS_CONFIG CODA_CORPUS_OUT_DIR" in generated_makefile
    assert (
        "`make profile-coda-corpus` reads `CODA_CORPUS_CONFIG` from `.env`."
    ) in generated_readme
    assert (
        "set `CODA_CORPUS_CONFIG` in `.env`, then run `make profile-coda-corpus`."
    ) in generated_operator_doc
    assert (output_dir / "config" / "coda_corpus.local.json").exists()
    assert (output_dir / "config" / "coda_live.local.json").exists()
