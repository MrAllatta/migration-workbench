"""Shared corpus pipeline utilities.

Provider-agnostic helpers for artifact I/O, slug generation,
heuristics normalization, and keyword matching.  Used by both
Sheets and Coda adapters.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def write_json(path: Path, payload: dict) -> None:
    """Create parent directories if needed and write *payload* as pretty-printed JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def make_slug(text: str) -> str:
    """Convert arbitrary text into a filesystem-safe slug (max 50 chars).

    Lowercase alphanumeric + underscores. Falls back to ``"tab"`` if empty.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug[:50] or "tab"


def token_match(token: str, text: str, mode: str) -> bool:
    """Check if *token* appears in *text* according to *mode*.

    Args:
        token: The keyword to look for (already lowered).
        text: The target string (already lowered).
        mode: ``"substring"`` (default) or ``"word"``.

    Returns:
        Whether a match was found.
    """
    if mode == "word":
        return bool(re.search(rf"\b{re.escape(token)}\b", text))
    return token in text


def normalize_tab_heuristics(config: dict | None) -> dict:
    """Normalise user-provided tab-scoring heuristics, filling defaults."""
    config = config or {}

    operational_weight = config.get("operational_weight", 3)
    reference_weight = config.get("reference_weight", 3)
    derived_weight = config.get("derived_weight", -4)
    support_weight = config.get("support_weight", -2)
    reference_combo_weight = config.get("reference_combo_weight", reference_weight)
    match_mode = config.get("match_mode", "substring")
    if match_mode not in ("substring", "word"):
        match_mode = "substring"

    combo_tokens: list[tuple[str, ...]] = []
    for entry in config.get("reference_combo_tokens") or []:
        if isinstance(entry, (list, tuple)) and all(
            isinstance(token, str) for token in entry
        ):
            combo_tokens.append(tuple(token.lower() for token in entry))
    tab_exclude_regexes: list[re.Pattern] = []
    exclude_patterns: list[dict] = []
    for entry in config.get("tab_exclude_patterns") or []:
        if isinstance(entry, dict) and "pattern" in entry:
            try:
                compiled = re.compile(entry["pattern"])
                if entry.get("exclude", False):
                    tab_exclude_regexes.append(compiled)
                else:
                    penalty = int(entry.get("penalty", -5))
                    exclude_patterns.append({"pattern": compiled, "penalty": penalty})
            except re.error:
                pass  # invalid regex silently skipped
    return {
        "operational_tokens": [
            token.lower()
            for token in (config.get("operational_tokens") or [])
            if isinstance(token, str)
        ],
        "reference_tokens": [
            token.lower()
            for token in (config.get("reference_tokens") or [])
            if isinstance(token, str)
        ],
        "reference_combo_tokens": combo_tokens,
        "support_tokens": [
            token.lower()
            for token in (config.get("support_tokens") or [])
            if isinstance(token, str)
        ],
        "derived_tokens": [
            token.lower()
            for token in (config.get("derived_tokens") or [])
            if isinstance(token, str)
        ],
        "operational_weight": operational_weight,
        "reference_weight": reference_weight,
        "derived_weight": derived_weight,
        "support_weight": support_weight,
        "reference_combo_weight": reference_combo_weight,
        "match_mode": match_mode,
        "tab_exclude_regexes": tab_exclude_regexes,
        "exclude_patterns": exclude_patterns,
        "expansion_formula_penalty": int(config.get("expansion_formula_penalty", 0)),
        "expansion_formula_threshold": float(
            config.get("expansion_formula_threshold", 0.5)
        ),
    }


def normalize_column_heuristics(config: dict | None) -> dict:
    """Normalise user-provided column-scoring heuristics, filling defaults."""
    config = config or {}
    return {
        "domain_keyword_tokens": [
            token.lower()
            for token in (config.get("domain_keyword_tokens") or [])
            if isinstance(token, str)
        ]
    }
