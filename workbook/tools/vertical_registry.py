"""Vertical template registry for domain-specific schema contract presets.

A *vertical template* bundles reusable defaults — entity templates, domain
context, interaction defaults, and signal thresholds — that accelerate schema
contract scaffolding for a known domain such as farming, retail, or logistics.

Merge priority (highest wins)
-----------------------------
1. **User / contract table** (explicit field definitions)
2. **Vertical template** (domain-specific defaults)
3. **Workbench default** (generic fallbacks)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class VerticalTemplate:
    """A loaded vertical template with mergeable defaults.

    Attributes:
        name: Short identifier for the vertical (e.g. ``"farm"``).
        version: Semver string for the template revision.
        description: Human-readable summary of the vertical's scope.
        domain_context: Optional vocabulary, entity definitions, and glossary
            for the domain.
        entity_templates: Mapping of model name → partial contract-table dict.
            Each entry supplies default columns, admin config, import config, etc.
        interaction_defaults: Optional role → archetype / tab mappings.
        signal_thresholds: Optional overrides for profiler signal thresholds.
        confidence: Confidence level: ``"exploratory"``, ``"medium"``, or
            ``"high"``.
    """

    name: str
    version: str
    description: str
    domain_context: dict | None = None
    entity_templates: dict[str, dict] | None = None
    interaction_defaults: dict | None = None
    signal_thresholds: dict | None = None
    confidence: str = "exploratory"


def _get_verticals_package_path() -> Path:
    """Resolve the filesystem path to the ``workbook.verticals`` package.

    Uses ``importlib.resources`` when available, falling back to a path
    relative to this file.
    """
    try:
        import importlib.resources as importlib_resources

        ref = importlib_resources.files("workbook.verticals")
        # importlib.resources may return a Traversable; convert to Path.
        return Path(str(ref))
    except (ImportError, ModuleNotFoundError, TypeError):
        return Path(__file__).resolve().parent.parent / "verticals"


def _load_manifest_from_path(manifest_path: Path) -> dict[str, Any]:
    """Load and validate a vertical manifest YAML file.

    Args:
        manifest_path: Absolute path to a ``manifest.yaml`` file.

    Returns:
        Parsed manifest dict.

    Raises:
        FileNotFoundError: If *manifest_path* does not exist.
        ValueError: If the manifest is missing required fields
            (``name``, ``version``, ``description``).
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Vertical manifest not found: {manifest_path}")

    with manifest_path.open(encoding="utf-8") as file_handle:
        manifest = yaml.safe_load(file_handle) or {}

    for required_field in ("name", "version", "description"):
        if required_field not in manifest:
            raise ValueError(
                f"Vertical manifest {manifest_path} is missing required "
                f"field: {required_field!r}"
            )

    return manifest


def discover_verticals(
    *,
    vertical_dir: str | Path | None = None,
) -> list[dict]:
    """Scan package-embedded and user-supplied directories for verticals.

    Discovery looks in two locations:
    1. The ``workbook.verticals`` package directory (built-in).
    2. An optional *vertical_dir* on the filesystem (user-supplied).

    Args:
        vertical_dir: Optional path to a directory of user-supplied vertical
            template directories.

    Returns:
        List of ``{name, version, description, confidence, source}`` dicts.
    """
    discovered: dict[str, dict] = {}

    # 1. Scan the package-embedded verticals directory.
    package_root = _get_verticals_package_path()
    _scan_directory(package_root, "package", discovered)

    # 2. Scan user-supplied directory.
    if vertical_dir:
        user_path = (
            Path(vertical_dir) if isinstance(vertical_dir, str) else vertical_dir
        )
        _scan_directory(user_path, "user", discovered)

    return list(discovered.values())


def _scan_directory(
    base_dir: Path,
    source_label: str,
    accumulator: dict[str, dict],
) -> None:
    """Scan a directory for vertical manifests and update *accumulator*.

    Each subdirectory of *base_dir* that contains a ``manifest.yaml`` is
    treated as a vertical template.

    Args:
        base_dir: Directory to scan for vertical subdirectories.
        source_label: Value for the ``"source"`` key (e.g. ``"package"``).
        accumulator: Dict keyed by vertical name, mutated in place.
    """
    if not base_dir.is_dir():
        return
    for child in sorted(base_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        manifest_file = child / "manifest.yaml"
        if not manifest_file.is_file():
            continue
        try:
            manifest = _load_manifest_from_path(manifest_file)
        except (FileNotFoundError, ValueError):
            continue
        key = manifest["name"]
        # User source wins over package source.
        if key not in accumulator or source_label == "user":
            accumulator[key] = {
                "name": manifest["name"],
                "version": manifest["version"],
                "description": manifest.get("description", ""),
                "confidence": manifest.get("confidence", "exploratory"),
                "source": source_label,
            }


def _load_from_package(name: str) -> dict[str, Any]:
    """Load a vertical manifest from the package-embedded directory.

    Args:
        name: Vertical name matching a subdirectory under
            ``workbook/verticals/``.

    Returns:
        Parsed manifest dict.

    Raises:
        FileNotFoundError: If no matching vertical is found in the package.
    """
    package_root = _get_verticals_package_path()
    candidate = package_root / name / "manifest.yaml"
    return _load_manifest_from_path(candidate)


def _normalise_null_keys(data: Any) -> Any:
    """Recursively replace YAML ``None`` keys with the string ``"null"``.

    PyYAML (and most YAML 1.1 parsers) interpret the bare word ``null`` as the
    YAML null value, producing a Python ``None`` dict key where the author
    intended the string ``"null"`` (e.g. ``null: true`` in field kwargs).
    """
    if isinstance(data, dict):
        return {
            ("null" if key is None else key): _normalise_null_keys(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_normalise_null_keys(item) for item in data]
    return data


def _manifest_to_template(manifest: dict[str, Any]) -> VerticalTemplate:
    """Convert a parsed manifest dict to a VerticalTemplate instance.

    Args:
        manifest: Parsed manifest dict from ``_load_manifest_from_path``.

    Returns:
        Populated ``VerticalTemplate``.
    """
    # YAML parses ``null:`` as a Python ``None`` key — normalise so that
    # downstream callers always see the string ``"null"``.
    entity_templates = _normalise_null_keys(manifest.get("entity_templates"))
    return VerticalTemplate(
        name=manifest["name"],
        version=manifest["version"],
        description=manifest.get("description", ""),
        domain_context=manifest.get("domain_context"),
        entity_templates=entity_templates,
        interaction_defaults=manifest.get("interaction_defaults"),
        signal_thresholds=manifest.get("signal_thresholds"),
        confidence=manifest.get("confidence", "exploratory"),
    )


def _merge_two_manifests(
    package_manifest: dict[str, Any],
    user_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Merge a user manifest over a package manifest (user wins).

    Shallow merge at the top level, except for ``entity_templates`` where
    per-entity keys are merged with user entities winning.
    """
    merged = dict(package_manifest)
    for key, user_value in user_manifest.items():
        if key == "entity_templates" and isinstance(user_value, dict):
            existing = merged.get("entity_templates", {})
            if isinstance(existing, dict):
                existing.update(user_value)
            merged["entity_templates"] = existing
        else:
            merged[key] = user_value
    return merged


def load_vertical(
    name: str,
    *,
    vertical_dir: str | Path | None = None,
) -> VerticalTemplate:
    """Load a vertical template with merge priority: user > package.

    Args:
        name: Vertical name (e.g. ``"example"``).
        vertical_dir: Optional path to a directory of user-supplied vertical
            templates.  If provided, any vertical with the same *name* in the
            user directory overrides the package-embedded version.

    Returns:
        VerticalTemplate with all fields merged (user over package).

    Raises:
        FileNotFoundError: If no template for *name* exists in either the
            package directory or the user-supplied directory.
    """
    # 1. Try to load from package directory.
    package_manifest = None
    try:
        package_manifest = _load_from_package(name)
    except FileNotFoundError:
        pass

    # 2. Try to load from user-supplied directory.
    user_manifest = None
    if vertical_dir:
        user_base = (
            Path(vertical_dir) if isinstance(vertical_dir, str) else vertical_dir
        )
        user_manifest_path = user_base / name / "manifest.yaml"
        try:
            user_manifest = _load_manifest_from_path(user_manifest_path)
        except FileNotFoundError:
            pass

    # 3. Neither found?
    if package_manifest is None and user_manifest is None:
        searched_parts = []
        if package_manifest is False:
            try:
                import importlib.resources as importlib_resources

                pkg = importlib_resources.files("workbook.verticals")
            except Exception:
                pkg = Path(__file__).resolve().parent.parent / "verticals"
            searched_parts.append(f"package:{pkg!s}")
        if vertical_dir:
            searched_parts.append(f"user:{vertical_dir!s}")
        searched = ", ".join(searched_parts) or "(default paths)"
        raise FileNotFoundError(f"Vertical template {name!r} not found in: {searched}")

    # 4. Merge: user wins over package.
    if user_manifest is not None and package_manifest is not None:
        merged_dict = _merge_two_manifests(package_manifest, user_manifest)
    elif user_manifest is not None:
        merged_dict = user_manifest
    else:
        merged_dict = package_manifest

    # merged_dict is guaranteed non-None here because we checked above.
    assert merged_dict is not None
    return _manifest_to_template(merged_dict)


def merge_entity_template(
    contract_table: dict[str, Any],
    entity_template: dict[str, Any],
) -> dict[str, Any]:
    """Merge an entity template into a contract table.

    Merge priority (highest wins):
    1. Existing ``contract_table`` fields (user / explicit) — field-level
       properties like ``django_field_class``, ``max_length``, etc. are
       preserved when the field already exists in the table.
    2. Entity template fields — added for new fields not in the contract.
    3. Workbench defaults — implicit.

    The merge operates on these known keys:
    - ``columns`` — field list; existing fields keep their properties,
      template fields are added for new field names.
    - ``admin`` — template admin block is added if not present.
    - ``import_config`` — template import config is added if not present.
    - ``model_meta`` — template model meta is added if not present.

    Args:
        contract_table: Existing contract table dict (from schema contract).
        entity_template: Partial entity template dict from a vertical.

    Returns:
        Merged contract table dict.
    """
    result = dict(contract_table)

    # -- Known keys to merge. --
    _merge_columns(result, entity_template)
    _merge_if_missing(result, entity_template, "admin")
    _merge_if_missing(result, entity_template, "import_config")
    _merge_if_missing(result, entity_template, "model_meta")

    return result


def _merge_columns(
    result: dict[str, Any],
    entity_template: dict[str, Any],
) -> None:
    """Merge columns from the entity template into *result*.

    Columns that already exist in *result* by name keep their properties
    (user wins).  Columns present only in the template are appended.
    """
    existing = result.get("columns") or []
    template_cols = entity_template.get("columns") or []

    if not template_cols:
        return

    # Index existing columns by name for fast lookup.
    existing_by_name: dict[str, dict[str, Any]] = {}
    for col in existing:
        name = col.get("suggested_field_name", col.get("source_column", ""))
        if name:
            existing_by_name[name] = col

    merged = list(existing)
    for tcol in template_cols:
        tname = tcol.get("name", "")
        if not tname:
            continue
        if tname in existing_by_name:
            # Field already exists — user's version wins; nothing to do.
            continue
        # New field from template: convert to contract-column format.
        new_col: dict[str, Any] = {
            "suggested_field_name": tname,
            "source_column": tcol.get("name", tname),
            "django_field_class": _template_type_to_django_class(
                tcol.get("data_type", "CharField")
            ),
            "django_field_kwargs": _extract_kwargs(tcol),
        }
        merged.append(new_col)

    result["columns"] = merged


def _template_type_to_django_class(data_type: str) -> str:
    """Convert a template data_type to a ``django_field_class`` string.

    Args:
        data_type: Short type name like ``"CharField"``, ``"IntegerField"``.

    Returns:
        Full Django field class like ``"models.CharField"``.
    """
    return f"models.{data_type}"


def _extract_kwargs(tcol: dict[str, Any]) -> dict[str, Any]:
    """Extract Django field kwargs from a template column definition.

    Removes the ``name`` and ``data_type`` keys, keeping everything else
    (``max_length``, ``null``, ``default``, ``unique``, etc.) as kwargs.
    """
    kwargs: dict[str, Any] = {}
    for key, value in tcol.items():
        if key in ("name", "data_type"):
            continue
        kwargs[key] = value
    return kwargs


def _merge_if_missing(
    result: dict[str, Any],
    entity_template: dict[str, Any],
    key: str,
) -> None:
    """Copy *key* from entity_template to result if not already present.

    Does nothing if *result* already has a non-None value for *key*.
    """
    if key not in result or result[key] is None:
        template_value = entity_template.get(key)
        if template_value is not None:
            result[key] = (
                dict(template_value)
                if isinstance(template_value, dict)
                else template_value
            )


# ---------------------------------------------------------------------------
# Template match suggestions (Phase 3)
# ---------------------------------------------------------------------------

GENERIC_HEADERS: set[str] = {"notes", "date", "id", "name"}
"""Headers excluded from column-overlap scoring because they are too generic."""

MIN_CONFIDENCE_THRESHOLD: float = 0.5
"""Minimum confidence score for a template suggestion to be actionable."""


def score_tab_against_templates(
    tab_title: str,
    column_headers: list[str],
    vertical: VerticalTemplate,
) -> list[dict]:
    """Score a tab against all entity templates in a vertical.

    Computes a combined confidence score from:
    (a) *Tab title keyword overlap* — how well the tab title matches the
        entity name or its declared keywords (0.0 – 1.0).
    (b) *Column header overlap* — what fraction of the entity template's
        non-generic field names appear among the tab's column headers
        (0.0 – 1.0).

    The final confidence is a weighted average: 40 % title score +
    60 % field-score.

    Generic headers (``"notes"``, ``"date"``, ``"id"``, ``"name"``) are
    excluded from column-overlap scoring to avoid false positives.

    Args:
        tab_title: Display title of the worksheet tab.
        column_headers: Column header strings from the tab.
        vertical: A loaded :class:`VerticalTemplate` whose
            ``entity_templates`` will be scored.

    Returns:
        List of ``{entity_name, confidence, matched_headers,
        unmatched_headers}`` dicts sorted by *confidence* descending.
        All scores are returned regardless of threshold; callers should
        filter with :const:`MIN_CONFIDENCE_THRESHOLD` where appropriate.
    """
    results: list[dict] = []
    entity_templates = vertical.entity_templates or {}
    if not entity_templates:
        return results

    # Build keyword lookup from domain-context entities.
    entity_keywords: dict[str, set[str]] = {}
    if vertical.domain_context:
        for entry in vertical.domain_context.get("entities", []):
            entity_name = entry.get("name", "")
            raw_keywords = entry.get("keywords", [])
            if entity_name:
                entity_keywords[entity_name] = {kw.lower() for kw in raw_keywords}

    title_lower = tab_title.lower()
    headers_lower: set[str] = {
        h.lower() for h in column_headers if h.lower() not in GENERIC_HEADERS
    }

    for entity_name, entity_data in entity_templates.items():
        # --- Title score ---
        entity_name_lower = entity_name.lower()
        title_score = _compute_title_score(
            title_lower,
            entity_name_lower,
            entity_keywords.get(entity_name, set()),
        )

        # --- Field score ---
        template_fields = _extract_template_fields(entity_data)
        matched = template_fields & headers_lower
        unmatched = template_fields - headers_lower

        field_score = 0.0
        if template_fields:
            field_score = len(matched) / len(template_fields)

        # Combined confidence (weighted average).
        confidence = round(0.4 * title_score + 0.6 * field_score, 2)

        results.append(
            {
                "entity_name": entity_name,
                "confidence": confidence,
                "matched_headers": sorted(matched),
                "unmatched_headers": sorted(unmatched),
            }
        )

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results


def _compute_title_score(
    title_lower: str,
    entity_name_lower: str,
    keywords: set[str],
) -> float:
    """Compute title-overlap score on a 0.0 – 1.0 scale.

    An exact match (or full substring containment) of the entity name
    within the tab title scores 1.0.  Otherwise the score is the fraction
    of keywords present in the title.
    """
    if entity_name_lower in title_lower:
        return 1.0

    # Check whether every word of a multi-word entity name appears.
    name_words = entity_name_lower.split()
    if name_words and all(word in title_lower for word in name_words):
        return 0.8

    if keywords:
        matched = sum(1 for kw in keywords if kw in title_lower)
        return matched / len(keywords)

    return 0.0


def _extract_template_fields(entity_data: dict) -> set[str]:
    """Return the set of non-generic field names from an entity template.

    Uses :const:`GENERIC_HEADERS` to filter out common generic column
    names.
    """
    fields: set[str] = set()
    for col in entity_data.get("columns") or []:
        name = (col.get("name") or "").lower()
        if name and name not in GENERIC_HEADERS:
            fields.add(name)
    return fields


def apply_vertical_to_schema(
    schema_contract: dict[str, Any],
    vertical: VerticalTemplate,
    *,
    tab_title_to_model: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply vertical entity templates to a schema contract.

    For each table in the schema contract, if the ``model_name`` matches an
    entity template in *vertical*, the template is merged into the table via
    :func:`merge_entity_template`.

    Args:
        schema_contract: The built schema contract dict (``{"tables": [...]}``).
        vertical: Loaded vertical template with ``entity_templates``.
        tab_title_to_model: Optional mapping of tab title to model name.
            Used when the scaffold has already assigned model names.

    Returns:
        Enriched schema contract dict (a deep copy with modifications).
    """
    import copy

    enriched = copy.deepcopy(schema_contract)

    entity_templates = vertical.entity_templates or {}
    if not entity_templates:
        return enriched

    # Build a lookup from tab title to model name if provided.
    tab_model_lookup: dict[str, str] = dict(tab_title_to_model or {})

    for table in enriched.get("tables", []):
        model_name = table.get("model_name", "")

        # Also check tab title mapping.
        if not model_name:
            tab_title = table.get("bundle_worksheet_title", "")
            model_name = tab_model_lookup.get(tab_title, "")

        # Check for direct match.
        entity_template = entity_templates.get(model_name)
        if entity_template is None:
            # Try case-insensitive match.
            for entity_name, entity_data in entity_templates.items():
                if entity_name.lower() == model_name.lower():
                    entity_template = entity_data
                    break

        if entity_template is not None:
            table.update(merge_entity_template(table, entity_template))

    return enriched


def apply_vertical_domain_context(
    vertical: VerticalTemplate,
    existing_domain_context: dict | None = None,
) -> dict:
    """Merge vertical domain context with existing (user) context.

    Strategy: shallow merge at the top level, then deep merge
    ``vocabulary``, ``entities``, and ``glossary`` sub-keys with
    existing (user) values winning on conflict.

    Args:
        vertical: Loaded vertical template with ``domain_context``.
        existing_domain_context: Optional existing domain context dict
            from a previous run or user override.

    Returns:
        Merged domain context dict with ``vocabulary``, ``entities``,
        and ``glossary`` keys.
    """
    vertical_context = dict(vertical.domain_context or {})
    existing = dict(existing_domain_context or {})

    merged = dict(vertical_context)
    merged.update(existing)

    for sub_key in ("vocabulary", "entities", "glossary"):
        existing_sub = existing.get(sub_key)
        vertical_sub = vertical_context.get(sub_key)
        if existing_sub is not None and vertical_sub is not None:
            if isinstance(existing_sub, dict) and isinstance(vertical_sub, dict):
                merged_sub = dict(vertical_sub)
                merged_sub.update(existing_sub)
                merged[sub_key] = merged_sub
            elif isinstance(existing_sub, list) and isinstance(vertical_sub, list):
                seen_key: set[str] = set()
                deduped: list = []
                for item in existing_sub:
                    key = str(item)
                    if key not in seen_key:
                        seen_key.add(key)
                        deduped.append(item)
                for item in vertical_sub:
                    key = str(item)
                    if key not in seen_key:
                        seen_key.add(key)
                        deduped.append(item)
                merged[sub_key] = deduped

    return merged
