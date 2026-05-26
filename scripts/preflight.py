import sys
from pathlib import Path
import shutil
import yaml


VENV_DIR = Path(".venv")
WB_PATH = VENV_DIR / "bin" / "wb"
DOMAIN_CONTEXT_PATH = Path("config/domain_context.yaml")

FAIL_MESSAGES = {
    "PREFLIGHT_VENV_MISSING": "Virtual environment .venv directory not found",
    "PREFLIGHT_WB_NOT_FOUND": "wb CLI not found on PATH or at .venv/bin/wb",
    "PREFLIGHT_CONFIG_MISSING": "config/domain_context.yaml not found",
    "PREFLIGHT_CONFIG_EMPTY": "config/domain_context.yaml is empty YAML",
    "PREFLIGHT_DOMAIN_EMPTY": "config/domain_context.yaml has empty 'domain' field",
    "PREFLIGHT_YEAR_SCOPE_EMPTY": "config/domain_context.yaml has empty 'year_scope.active' list",
    "PREFLIGHT_VOCABULARY_EMPTY": "config/domain_context.yaml has no operational or reference vocabulary",
}


def check_venv():
    if not VENV_DIR.exists():
        print(
            f"FAIL[PREFLIGHT_VENV_MISSING]: {FAIL_MESSAGES['PREFLIGHT_VENV_MISSING']}"
        )
        print(
            "  → Action: Run `make install` or create .venv with `python -m venv .venv`"
        )
        sys.exit(1)
    return True


def check_wb():
    if shutil.which("wb") is None and not WB_PATH.exists():
        print(
            f"FAIL[PREFLIGHT_WB_NOT_FOUND]: {FAIL_MESSAGES['PREFLIGHT_WB_NOT_FOUND']}"
        )
        print(
            "  → Action: Ensure wb CLI is installed and on PATH, or run `make install`"
        )
        sys.exit(1)
    return True


def check_domain_context():
    if not DOMAIN_CONTEXT_PATH.exists():
        print(
            f"FAIL[PREFLIGHT_CONFIG_MISSING]: {FAIL_MESSAGES['PREFLIGHT_CONFIG_MISSING']}"
        )
        print("  → Action: Create config/domain_context.yaml with required fields")
        sys.exit(1)

    try:
        with open(DOMAIN_CONTEXT_PATH) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        print(
            f"FAIL[PREFLIGHT_CONFIG_EMPTY]: {FAIL_MESSAGES['PREFLIGHT_CONFIG_EMPTY']}"
        )
        print("  → Action: Fix YAML syntax in config/domain_context.yaml")
        sys.exit(1)

    if not data:
        print(
            f"FAIL[PREFLIGHT_CONFIG_EMPTY]: {FAIL_MESSAGES['PREFLIGHT_CONFIG_EMPTY']}"
        )
        print("  → Action: Add non-empty 'domain' field to config/domain_context.yaml")
        sys.exit(1)

    if not data.get("domain"):
        print(
            f"FAIL[PREFLIGHT_DOMAIN_EMPTY]: {FAIL_MESSAGES['PREFLIGHT_DOMAIN_EMPTY']}"
        )
        print("  → Action: Add non-empty 'domain' field to config/domain_context.yaml")
        sys.exit(1)

    if not data.get("year_scope", {}).get("active"):
        print(
            f"FAIL[PREFLIGHT_YEAR_SCOPE_EMPTY]: {FAIL_MESSAGES['PREFLIGHT_YEAR_SCOPE_EMPTY']}"
        )
        print(
            "  → Action: Add non-empty 'year_scope.active' list to config/domain_context.yaml"
        )
        sys.exit(1)

    operational = data.get("vocabulary", {}).get("operational", [])
    reference = data.get("vocabulary", {}).get("reference", [])
    if not operational and not reference:
        print(
            f"FAIL[PREFLIGHT_VOCABULARY_EMPTY]: {FAIL_MESSAGES['PREFLIGHT_VOCABULARY_EMPTY']}"
        )
        print(
            "  → Action: Add at least one token to 'vocabulary.operational' or 'vocabulary.reference'"
        )
        sys.exit(1)

    return True


def main():
    check_venv()
    check_wb()
    check_domain_context()
    print("PASS: preflight checks OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
