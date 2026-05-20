"""Profiler enrichment utilities for FK detection, computed fields, and entity grouping."""

_ENTITY_KEYWORDS = {"channel", "season", "crop", "block", "farm", "field", "variety"}
_IDENTIFIER_SUFFIXES = {"_id", "_code", "_key"}
_IDENTIFIER_NAMES = {"id", "name", "code", "slug", "uid", "uuid", "external_id"}


def _to_pascal_case(raw: str) -> str:
    """Convert a label to PascalCase.

    If the input is already PascalCase (no underscores/hyphens, has uppercase
    after position 0), pass it through unchanged.
    """
    if not raw:
        return raw
    if "_" not in raw and "-" not in raw and any(c.isupper() for c in raw[1:]):
        return raw
    return "".join(p.capitalize() for p in raw.replace("-", "_").split("_"))


def glossary_expand(text: str, glossary: dict[str, str]) -> set[str]:
    """Return expanded forms of glossary keys found in *text*."""
    lowered = text.lower()
    expansions: set[str] = set()
    for abbr, full_form in glossary.items():
        if abbr.lower() in lowered:
            expansions.add(full_form.lower())
    return expansions
