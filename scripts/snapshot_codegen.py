"""Snapshot-generated codegen output for regression detection.

Usage::

    # Take new snapshots
    python scripts/snapshot_codegen.py --snapshot path/to/contract.yaml

    # Check against existing snapshots (CI mode)
    python scripts/snapshot_codegen.py --check path/to/contract.yaml

Snapshots are stored in ``build/codegen-snapshots/<version>/``.
``--check`` regenerates and diffs against stored snapshots, exiting 1
on any difference.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

from workbook.codegen.admin_generator import render_admin_py
from workbook.codegen.contract import load_contract
from workbook.codegen.import_generator import render_import_py
from workbook.codegen.model_generator import render_models_py


def _version_dir(contract: dict, base: Path) -> Path:
    version = contract.get("version", "unknown")
    return base / f"v{version}"


def _generate_all(contract: dict, app_label: str) -> dict[str, str]:
    return {
        "models.py": render_models_py(contract, app_label=app_label),
        "admin.py": render_admin_py(contract, manifest=None, app_label=app_label),
        "import.py": render_import_py(contract, app_label=app_label),
    }


def _take_snapshot(
    contract_path: Path,
    contract: dict,
    out_dir: Path,
    app_label: str,
) -> int:
    version_dir = _version_dir(contract, out_dir)
    version_dir.mkdir(parents=True, exist_ok=True)

    files = _generate_all(contract, app_label)
    for name, content in sorted(files.items()):
        target = version_dir / name
        existed = target.exists()
        target.write_text(content, encoding="utf-8")
        label = "overwritten" if existed else "written"
        print(f"  {label}: {target}")

    model_count = len(contract.get("tables") or [])
    print(f"snapshot v{contract['version']} ({model_count} model(s)): {version_dir}")
    return 0


def _check_snapshot(
    contract_path: Path,
    contract: dict,
    out_dir: Path,
    app_label: str,
) -> int:
    version_dir = _version_dir(contract, out_dir)
    if not version_dir.is_dir():
        print(f"no snapshot directory: {version_dir}")
        print("run with --snapshot first")
        return 1

    files = _generate_all(contract, app_label)
    exit_code = 0
    for name, content in sorted(files.items()):
        snapshot_path = version_dir / name
        if not snapshot_path.is_file():
            print(f"MISSING: {snapshot_path}")
            exit_code = 1
            continue
        current = snapshot_path.read_text(encoding="utf-8")
        if current == content:
            print(f"  OK: {name}")
        else:
            diff = difflib.unified_diff(
                current.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=str(snapshot_path),
                tofile="<generated>",
            )
            diff_text = "".join(diff)
            print(f"  DIFF: {name}")
            print(diff_text[:2000])
            exit_code = 1

    if exit_code == 0:
        print(f"all snapshots match for v{contract['version']}")
    return exit_code


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Snapshot or check codegen output for regression detection."
    )
    parser.add_argument("contract", help="Path to schema-contract YAML")
    parser.add_argument(
        "--out-dir",
        default="build/codegen-snapshots",
        help="Snapshot root directory (default: build/codegen-snapshots)",
    )
    parser.add_argument(
        "--app-label",
        default="core",
        help="Django app label (default: core)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--snapshot",
        action="store_true",
        help="Take new snapshots (overwrites existing)",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Check generated output against existing snapshots",
    )

    args = parser.parse_args()
    contract_path = Path(args.contract).resolve()
    if not contract_path.is_file():
        print(f"contract not found: {contract_path}")
        return 1

    try:
        contract = load_contract(str(contract_path))
    except ValueError as exc:
        print(f"error loading contract: {exc}")
        return 1

    out_dir = Path(args.out_dir).resolve()
    app_label = args.app_label

    if args.snapshot:
        return _take_snapshot(contract_path, contract, out_dir, app_label)
    elif args.check:
        return _check_snapshot(contract_path, contract, out_dir, app_label)
    return 1


if __name__ == "__main__":
    sys.exit(main())
