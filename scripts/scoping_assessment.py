"""CLI tool that profiles spreadsheet complexity and produces a scoping estimate.

Usage:
    python scripts/scoping_assessment.py --profile profiler_output.json
    python scripts/scoping_assessment.py --source "https://sheets.google.com/..."
"""

import json
import argparse
from pathlib import Path
from typing import Any


def assess_spreadsheet_complexity(profile: dict) -> dict[str, Any]:
    """Analyze a profiler output dict and return a complexity assessment."""
    tabs = profile.get("tabs", [])
    cross_sheet_refs = profile.get("cross_sheet_refs", [])

    tab_count = len(tabs)
    total_rows = sum(t.get("row_count", 0) for t in tabs)
    total_columns = sum(len(t.get("columns", [])) for t in tabs)
    total_formula_columns = sum(t.get("formula_columns", 0) for t in tabs)
    cross_ref_count = len(cross_sheet_refs)

    formula_density = total_formula_columns / max(total_columns, 1)

    # Complexity scoring
    score = 0
    if tab_count > 5:
        score += 1
    if tab_count > 10:
        score += 2
    if total_rows > 5000:
        score += 1
    if total_rows > 20000:
        score += 1
    if formula_density > 0.3:
        score += 1
    if cross_ref_count > 5:
        score += 1
    if cross_ref_count > 20:
        score += 2

    if score <= 2:
        complexity_tier = "appliance"
        estimated_build_weeks = 2
    elif score <= 5:
        complexity_tier = "partnership"
        estimated_build_weeks = score
    else:
        complexity_tier = "partnership"
        estimated_build_weeks = min(score + 2, 12)

    recommendation = (
        "Appliance — well-structured data, low formula complexity. Standard pipeline covers most needs."
        if complexity_tier == "appliance"
        else "Partnership — complex spreadsheet interdependency. Human contract hardening and domain modeling recommended."
    )

    return {
        "tab_count": tab_count,
        "total_rows": total_rows,
        "total_columns": total_columns,
        "formula_density": round(formula_density, 2),
        "cross_sheet_ref_count": cross_ref_count,
        "complexity_score": score,
        "complexity_tier": complexity_tier,
        "estimated_build_weeks": estimated_build_weeks,
        "recommendation": recommendation,
    }


def load_profile(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess spreadsheet complexity for scoping")
    parser.add_argument("--profile", type=Path, help="Path to profiler output JSON")
    args = parser.parse_args()

    if args.profile:
        profile = load_profile(args.profile)
    else:
        parser.print_help()
        return

    result = assess_spreadsheet_complexity(profile)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
