"""Load, normalise, and query a schema-contract YAML for code generation.

Provides a uniform access layer so generators don't need to branch on
contract features — accessor functions return sensible defaults for
absent keys.
"""

from __future__ import annotations

import re
from typing import Any

import networkx as nx

from workbook.contract.loading import (  # noqa: E402, F401
    _make_contract_loader,
    load_contract_unvalidated,
    load_contract,
)
from workbook.contract.accessors import (  # noqa: E402, F401
    _apply_field_override,
    _normalise_field_class,
    _resolve_fk_target,
    get_admin_config,
    get_auth_config,
    get_computed_fields,
    get_db_table_name,
    get_enums,
    get_extra_imports,
    get_hooks,
    get_import_config,
    get_is_abstract,
    get_model_base,
    get_model_meta,
    get_model_name,
    get_str_template,
    has_source_tab,
    get_fields,
    resolve_field_mapping,
)
from workbook.contract.validation import (  # noqa: E402, F401
    _validate_table_exceptions,
    validate_contract_tables,
    strict_validate_contract,
)
from workbook.contract.diff import (  # noqa: E402, F401
    MIGRATION_SEVERITY_DANGER,
    MIGRATION_SEVERITY_WARNING,
    _diff_fields,
    _diff_meta,
    _diff_tables,
    _field_map,
    _field_summary,
    diff_contracts,
    _field_class_short,
    migration_safety_checks,
)


def review_contract(
    contract: dict[str, Any],
    dependency_artifact: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Run a design-review checklist on a schema contract.

    Checks intended for schema designers before codegen — catches common
    pitfalls like nullable FKs without ``on_delete``, CharFields without
    ``max_length``, and missing ``unique_together`` on multi-FK tables.

    Returns:
        List of issue dicts. Each issue includes stable ``rule_id`` plus
        ``table``, ``field``, and ``message`` keys.
    """
    issues: list[dict[str, str]] = []
    tables = list(contract.get("tables") or [])
    table_names = {get_model_name(t) for t in tables}

    for table in tables:
        name = get_model_name(table)
        fields = get_fields(table)
        meta = table.get("model_meta") or {}

        suppressed_rule_ids = set(table.get("suppress_review_warnings") or [])

        def add_issue(rule_id: str, field: str, message: str) -> None:
            """Append a review issue unless suppressed by table-level config."""
            if rule_id in suppressed_rule_ids:
                return
            issues.append(
                {
                    "rule_id": rule_id,
                    "table": name,
                    "field": field,
                    "message": message,
                }
            )

        # Check: CharField without max_length.
        for field in fields:
            fclass = _field_class_short(field["class"])
            kwargs = field["kwargs"]
            if fclass == "CharField" and "max_length" not in kwargs:
                add_issue(
                    "charfield_missing_max_length",
                    field["name"],
                    "CharField without max_length — default will be used",
                )
            # Check: nullable FK without explicit on_delete.
            if fclass == "ForeignKey":
                on_delete = kwargs.get("on_delete")
                null_ok = kwargs.get("null", kwargs.get("blank", False))
                if null_ok and not on_delete:
                    add_issue(
                        "nullable_fk_missing_on_delete",
                        field["name"],
                        "nullable FK without explicit on_delete — Django will warn at runtime",
                    )
                elif null_ok and str(on_delete) == "PROTECT":
                    add_issue(
                        "nullable_fk_with_protect",
                        field["name"],
                        "nullable FK with PROTECT — import failures leave orphaned rows",
                    )

        # Check: multiple FK fields but no unique_together or constraints.
        fk_fields = [f for f in fields if f["class"] == "models.ForeignKey"]
        if len(fk_fields) >= 2:
            has_unique = bool(meta.get("unique_together") or meta.get("constraints"))
            if not has_unique:
                add_issue(
                    "multiple_fk_without_unique",
                    ", ".join(f["name"] for f in fk_fields),
                    "multiple FK fields but no unique_together or constraints — possible duplicate rows",
                )

        # Check: model has no __str__ template for admin usability.
        str_tmpl = table.get("str_template")
        if not str_tmpl:
            add_issue(
                "missing_str_template",
                "",
                "no str_template — admin lists show unhelpful object labels",
            )

        # Check: fk_lookup targets a model not in the contract.
        import_config = table.get("import_config") or {}
        fk_lookup = import_config.get("fk_lookup") or {}
        for field_name, lookup_def in fk_lookup.items():
            target_model = lookup_def.get("model", "")
            if target_model and target_model not in table_names:
                add_issue(
                    "fk_lookup_missing_target_model",
                    field_name,
                    f"fk_lookup references '{target_model}' which is not a table in the contract",
                )

        # Check: fk_lookup on a tab with no cross-sheet edges.
        if dependency_artifact:
            sheet_graph = dependency_artifact.get("sheet_graph", {})
            sheet_edges = sheet_graph.get("edges", [])
            if sheet_edges and fk_lookup:
                this_tab = table.get("bundle_worksheet_title", "")
                if this_tab:
                    tab_has_edges = any(
                        e.get("from_sheet") == this_tab or e.get("to_sheet") == this_tab
                        for e in sheet_edges
                    )
                    if not tab_has_edges:
                        add_issue(
                            "fk_lookup_no_cross_sheet_edge",
                            ", ".join(fk_lookup.keys()),
                            f"tab '{this_tab}' declares fk_lookup but has no"
                            f" cross-sheet edges in the dependency graph",
                        )

        # Check: admin.inlines target a model not in the contract.
        admin_config = table.get("admin") or {}
        for inline_name in admin_config.get("inlines") or []:
            if inline_name not in table_names:
                add_issue(
                    "admin_inline_missing_target_model",
                    inline_name,
                    f"admin.inlines references '{inline_name}' which is not a table in the contract",
                )

        # Check: computed_fields use snake_case names.
        computed = table.get("computed_fields") or {}
        for cf_name in computed:
            if not re.match(r"^[a-z][a-z0-9_]*$", cf_name):
                add_issue(
                    "computed_field_not_snake_case",
                    cf_name,
                    f"computed_field '{cf_name}' is not snake_case — use lowercase_with_underscores",
                )

    return issues


def assign_import_tiers(
    contract: dict[str, Any],
) -> dict[str, int]:
    """Auto-assign import tiers by topological sort of FK dependency chains.

    Tables with no FK dependencies get tier 1.  Each subsequent tier adds
    one.  If a table already has an explicit ``import_config.tier``, that
    value is preserved.

    Returns:
        ``{model_name: tier}`` for every table with ``import_config``.
    """
    tables = list(contract.get("tables") or [])
    table_names: dict[str, dict[str, Any]] = {}
    for t in tables:
        name = get_model_name(t)
        if get_import_config(t) is not None:
            table_names[name] = t

    # Build adjacency: model → set of FK target model names.
    deps: dict[str, set[str]] = {}
    for name, t in table_names.items():
        cfg = get_import_config(t)
        fk_lookup = (cfg or {}).get("fk_lookup") or {}
        targets: set[str] = set()
        for fk_cfg in fk_lookup.values():
            target = fk_cfg.get("model")
            if target and target in table_names:
                targets.add(target)
        deps[name] = targets

    G = nx.DiGraph()
    for name in table_names:
        G.add_node(name)
    for name, targets in deps.items():
        for dep in targets:
            G.add_edge(dep, name)

    tier_map: dict[str, int] = {}
    try:
        for tier, generation in enumerate(nx.topological_generations(G), start=1):
            for name in generation:
                tier_map[name] = tier
    except nx.NetworkXUnfeasible:
        pass

    # Apply explicit tiers as overrides.
    result: dict[str, int] = {}
    for name, t in table_names.items():
        cfg = get_import_config(t)
        explicit = cfg.get("tier") if cfg else None
        if explicit is not None:
            result[name] = int(explicit)
        else:
            result[name] = tier_map.get(name, 99)

    return result

