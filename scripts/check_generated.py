"""Run ``py_compile`` on one or more generated Python files.

Usage: python scripts/check_generated.py <file1.py> [file2.py ...]

Exits with code 0 when all files compile, 1 on any failure.
"""

import py_compile
import sys


def main() -> None:
    files = [f for f in sys.argv[1:] if f.strip()]
    if not files:
        print("Usage: python scripts/check_generated.py <file.py> [...]")
        sys.exit(1)

    exit_code = 0
    for path in files:
        try:
            py_compile.compile(path, doraise=True)
            print(f"OK: {path}")
        except py_compile.PyCompileError as exc:
            print(f"FAIL: {exc}")
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
