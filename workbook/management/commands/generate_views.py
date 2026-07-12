"""Emit Django ListView + template + URL patterns from a schema contract.

Reads a schema-contract YAML and (optionally) a view-manifest YAML, then
writes:

- ``views_auto.py``: ListView subclasses + HTMX toggle handlers, following
  the ``*_auto.py`` + stub convention from :mod:`workbook.codegen.stub_writer`
- ``urls_auto.py``: URL patterns wired to the auto views module
- ``<template_path>``: Django template under the configured output template
  directory

Use the ``--archetype-checklist`` flag (or ``--archetype``) to scope which
models get a weekly checklist view.  The flag accepts a comma-separated
list of ``AppLabel.ModelName`` strings.  A single auto file can hold
multiple archetypes.

Examples::

    # Generate a single checklist view for the PlantingPlan model.
    python manage.py generate_views \\
        --contract build/schema-contract.yaml \\
        --out-dir build/_out/generated_views \\
        --app-label core \\
        --archetype-checklist core.PlantingPlan \\
        --force

    # Generate checklist views for every model with a planned_year field.
    python manage.py generate_views \\
        --contract build/schema-contract.yaml \\
        --out-dir build/_out/generated_views \\
        --archetype-checklist auto \\
        --force
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from django.core.management.base import BaseCommand, CommandError

from workbook.codegen.contract import (
    load_contract_unvalidated,
    strict_validate_contract,
)
from workbook.codegen.view_generator import (
    AlertCard,
    ChecklistArchetype,
    ChecklistColumn,
    DashboardArchetype,
    DetailColumn,
    DetailSection,
    LandingArchetype,
    SummaryCard,
    build_archetype_from_contract,
    render_checklist_template_html,
    render_dashboard_template_html,
    render_dashboard_urls_auto_py,
    render_dashboard_views_auto_py,
    render_landing_template_html,
    render_landing_urls_auto_py,
    render_landing_views_auto_py,
    render_urls_auto_py,
    render_views_auto_py,
)


def _resolve_app_label(
    contract: dict[str, Any],
    explicit: str | None,
) -> str:
    """Resolve the app label from a contract's first table or CLI override."""
    if explicit:
        return explicit
    tables = contract.get("tables") or []
    if tables and isinstance(tables[0], dict):
        meta = tables[0].get("model_meta") or {}
        candidate = meta.get("app_label")
        if candidate:
            return str(candidate)
    return "core"


def _find_table_for_model(
    contract: dict[str, Any],
    model_name: str,
) -> dict[str, Any] | None:
    """Find a contract table by PascalCase model_name."""
    for table in contract.get("tables") or []:
        mname = table.get("model_name") or table.get("name")
        if mname == model_name:
            return table
    return None


def _table_has_planned_year_week(table: dict[str, Any]) -> bool:
    """Return True if a contract table has ``planned_year`` and
    ``planned_week`` fields (the canonical checklist week filter)."""
    field_names = set()
    for col in table.get("columns") or []:
        if not isinstance(col, dict):
            continue
        name = col.get("name") or col.get("suggested_field_name")
        if name:
            field_names.add(name)
    return {"planned_year", "planned_week"}.issubset(field_names)


def _parse_archetype_targets(
    raw: str,
) -> tuple[str, list[tuple[str, str]]]:
    """Parse the ``--archetype-checklist`` value.

    Returns:
        A tuple ``(mode, targets)`` where ``mode`` is either ``"explicit"``
        or ``"auto"`` and ``targets`` is a list of ``(app_label, model_name)``
        pairs.  For ``"auto"`` mode, ``targets`` is empty (the command
        iterates contract tables itself).
    """
    raw = raw.strip()
    if not raw:
        raise CommandError("--archetype-checklist requires a value")
    if raw.lower() == "auto":
        return ("auto", [])
    targets: list[tuple[str, str]] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "." not in token:
            raise CommandError(
                f"Invalid --archetype-checklist target: {token!r}. "
                "Use 'AppLabel.ModelName' or 'auto'."
            )
        app_label, model_name = token.split(".", 1)
        if not app_label or not model_name:
            raise CommandError(
                f"Invalid --archetype-checklist target: {token!r}. "
                "Both AppLabel and ModelName are required."
            )
        targets.append((app_label, model_name))
    return ("explicit", targets)


def _column_from_contract(
    table: dict[str, Any],
    max_count: int = 4,
) -> list[ChecklistColumn]:
    """Derive a :class:`ChecklistColumn` list from a contract table.

    Mirrors :func:`workbook.codegen.view_generator._auto_columns` but is
    importable from the management command without reaching into private
    helpers.
    """
    columns: list[ChecklistColumn] = []
    seen: set[str] = set()
    for col in table.get("columns") or []:
        if not isinstance(col, dict):
            continue
        field_name = col.get("name") or col.get("suggested_field_name")
        if not field_name or field_name in seen:
            continue
        seen.add(field_name)
        if field_name in (
            "planned_year", "planned_week", "seeding_year", "seeding_week"
        ):
            continue
        if field_name in ("id", "pk"):
            continue
        if len(columns) >= max_count:
            break
        label = col.get("header") or field_name.replace("_", " ").title()
        is_fk = (col.get("class") or "").endswith("ForeignKey")
        columns.append(
            ChecklistColumn(
                field=field_name,
                label=label,
                format="fk_display" if is_fk else "value",
            )
        )
    return columns


def _build_archetypes(
    contract: dict[str, Any],
    app_label_default: str,
    targets: Sequence[tuple[str, str]],
) -> list[ChecklistArchetype]:
    """Build checklist archetypes for the given (app_label, model_name) targets."""
    archetypes: list[ChecklistArchetype] = []
    for app_label, model_name in targets:
        table = _find_table_for_model(contract, model_name)
        if table is None:
            raise CommandError(
                f"Model {model_name!r} not found in contract. "
                "Available: "
                + ", ".join(
                    str(t.get("model_name") or t.get("name"))
                    for t in (contract.get("tables") or [])
                    if isinstance(t, dict)
                )
            )
        columns = _column_from_contract(table)
        archetype = build_archetype_from_contract(
            model=model_name,
            app_label=app_label,
            contract_table=table,
            columns=columns,
        )
        archetypes.append(archetype)
    return archetypes


def _auto_archetypes(
    contract: dict[str, Any],
    app_label_default: str,
) -> list[ChecklistArchetype]:
    """Auto-discover checklist archetypes for every contract table that
    has both ``planned_year`` and ``planned_week`` fields."""
    archetypes: list[ChecklistArchetype] = []
    for table in contract.get("tables") or []:
        if not isinstance(table, dict):
            continue
        if not _table_has_planned_year_week(table):
            continue
        model_name = table.get("model_name") or table.get("name")
        if not model_name:
            continue
        app_label = (
            (table.get("model_meta") or {}).get("app_label")
            or app_label_default
        )
        columns = _column_from_contract(table)
        archetype = build_archetype_from_contract(
            model=model_name,
            app_label=str(app_label),
            contract_table=table,
            columns=columns,
        )
        archetypes.append(archetype)
    return archetypes


def _template_output_path(
    out_dir: Path,
    template_path: str,
) -> Path:
    """Map a template path (``a/b/c.html``) to ``<out_dir>/a/b/c.html``."""
    return out_dir / template_path


def _write_file(path: Path, content: str, *, force: bool) -> bool:
    """Write ``content`` to ``path``, respecting ``force`` and existence.

    Returns ``True`` when the file was written, ``False`` when skipped.
    """
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _resolve_template_source(
    template_package: Path | None,
    out_dir: Path,
    template_path: str,
    default_source: str,
) -> str:
    """Return the template source to write for ``template_path``.

    If ``template_package`` is set and contains a file at the same relative
    path as ``template_path``, the product override is used instead of the
    generated default.  This lets product repos commit skinned templates in
    a template package directory while still generating views and URLs.
    """
    if template_package is None:
        return default_source
    override_path = template_package / template_path
    if override_path.is_file():
        return override_path.read_text(encoding="utf-8")
    return default_source


def _load_landing_config(path: Path) -> list[LandingArchetype]:
    """Load landing archetypes from a YAML config file.

    The config file should have a top-level ``landings`` list:

    .. code-block:: yaml

        landings:
          - role: field_worker
            title: "Field Ops"
            cards:
              - label: Open Tasks
                count_expression: TaskPlan.objects.filter(status='open').count()
                link_url_name: farm_ui_task_checklist
              - label: Low Inventory
                count_expression: "InventoryLedger.objects.filter(
                    Q(quantity_on_hand__lte=F('threshold')) |
                    Q(threshold__isnull=False, quantity_on_hand__isnull=True)
                ).count()"
                link_url_name: farm_ui_inventory
                css_class: card-warning
            back_url_name: farm_ui_root
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        raise CommandError("PyYAML is required for --archetype-landing")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "landings" not in raw:
        raise CommandError(
            "Landing config must have a top-level 'landings' list."
        )

    archetypes: list[LandingArchetype] = []
    for entry in raw["landings"]:
        if not isinstance(entry, dict):
            continue
        cards: list[SummaryCard] = []
        for card in entry.get("cards") or []:
            cards.append(
                SummaryCard(
                    label=str(card["label"]),
                    count_expression=str(card["count_expression"]),
                    link_url_name=str(card.get("link_url_name") or "") or None,
                    css_class=str(card.get("css_class") or ""),
                )
            )
        archetypes.append(
            LandingArchetype(
                role=str(entry["role"]),
                title=str(entry.get("title") or f"{entry['role']} Dashboard"),
                cards=cards,
                back_url_name=str(entry.get("back_url_name") or "") or None,
            )
        )
    return archetypes


def _load_dashboard_config(path: Path) -> list[DashboardArchetype]:
    """Load dashboard archetypes from a YAML config file.

    The config file should have a top-level ``dashboards`` list:

    .. code-block:: yaml

        dashboards:
          - name: inventory
            title: Inventory Dashboard
            alerts:
              - label: Zero Stock
                count_expression: InventoryLedger.objects.filter(quantity_on_hand=0).count()
                severity: warning
                link_url_name: farm_ui_inventory
              - label: Total Items
                count_expression: InventoryLedger.objects.count()
                severity: info
            sections:
              - title: Inventory Items
                queryset_expression: InventoryLedger.objects.select_related("crop").all()
                limit: 50
                empty_message: No inventory data.
                columns:
                  - field: crop
                    label: Crop
                    format: fk_display
                  - field: quantity_on_hand
                    label: On Hand
                    format: value
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        raise CommandError("PyYAML is required for --archetype-dashboard")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "dashboards" not in raw:
        raise CommandError(
            "Dashboard config must have a top-level 'dashboards' list."
        )

    archetypes: list[DashboardArchetype] = []
    for entry in raw["dashboards"]:
        if not isinstance(entry, dict):
            continue

        alerts: list[AlertCard] = []
        for alert in entry.get("alerts") or []:
            alerts.append(
                AlertCard(
                    label=str(alert["label"]),
                    count_expression=str(alert["count_expression"]),
                    severity=str(alert.get("severity") or "info"),
                    link_url_name=str(alert.get("link_url_name") or "") or None,
                )
            )

        sections: list[DetailSection] = []
        for sec in entry.get("sections") or []:
            columns: list[DetailColumn] = []
            for col in sec.get("columns") or []:
                columns.append(
                    DetailColumn(
                        field=str(col["field"]),
                        label=str(col["label"]),
                        format=str(col.get("format") or "value"),
                    )
                )
            sections.append(
                DetailSection(
                    title=str(sec["title"]),
                    queryset_expression=str(sec["queryset_expression"]),
                    columns=columns,
                    limit=sec.get("limit"),
                    empty_message=str(sec.get("empty_message") or "No records found."),
                )
            )

        archetypes.append(
            DashboardArchetype(
                name=str(entry["name"]),
                title=str(entry.get("title") or entry["name"]),
                alerts=alerts,
                sections=sections,
                back_url_name=str(entry.get("back_url_name") or "") or None,
                app_label=str(entry.get("app_label") or "core"),
                base_template=str(entry.get("base_template") or "base.html"),
            )
        )
    return archetypes


class Command(BaseCommand):
    help = (
        "Generate Django views + templates + URL patterns from schema "
        "contracts and config files. Supports checklist and landing archetypes."
    )

    def add_arguments(self, parser):
        """Register CLI flags."""
        parser.add_argument(
            "--contract",
            required=True,
            help="Path to schema-contract YAML (e.g. build/schema-contract.yaml)",
        )
        parser.add_argument(
            "--out-dir",
            required=True,
            help="Output directory for the generated views, URLs, and template files",
        )
        parser.add_argument(
            "--app-label",
            default=None,
            help="Django app label (default: first table's model_meta.app_label, fallback 'core')",
        )
        parser.add_argument(
            "--archetype-checklist",
            default=None,
            help=(
                "Checklist archetype target. 'auto' = every model with planned_year/week, "
                "or a comma-separated list of AppLabel.ModelName."
            ),
        )
        parser.add_argument(
            "--archetype",
            default=None,
            help="Alias for --archetype-checklist.",
        )
        parser.add_argument(
            "--archetype-landing",
            default=None,
            help=(
                "Path to a landing-config YAML. Generates TemplateView + "
                "template with summary cards from the config."
            ),
        )
        parser.add_argument(
            "--archetype-dashboard",
            default=None,
            help=(
                "Path to a dashboard-config YAML with a top-level 'dashboards' list. "
                "Generates TemplateView + template with alert cards and detail tables."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing output files without prompting",
        )
        parser.add_argument(
            "--validate",
            action="store_true",
            help="Strict-validate the contract before rendering",
        )
        parser.add_argument(
            "--template-package",
            default=None,
            help=(
                "Path to a product template package directory. "
                "If a template exists in the package at the same relative path "
                "as the generated template, the package override is used."
            ),
        )

    def handle(self, *args, **options):
        """Load the contract, resolve archetypes, and write outputs."""
        contract_path = Path(options["contract"]).resolve()
        if not contract_path.is_file():
            raise CommandError(f"contract not found: {contract_path}")
        try:
            contract = load_contract_unvalidated(str(contract_path))
        except Exception as exc:
            raise CommandError(f"failed to load contract: {exc}") from exc
        if options.get("validate"):
            errors = strict_validate_contract(contract)
            if errors:
                raise CommandError(
                    f"contract validation failed: {'; '.join(errors)}"
                )

        archetype_checklist = options.get("archetype_checklist") or options.get("archetype")
        archetype_landing = options.get("archetype_landing")
        archetype_dashboard = options.get("archetype_dashboard")

        if not archetype_checklist and not archetype_landing and not archetype_dashboard:
            raise CommandError(
                "specify at least one archetype flag: "
                "--archetype-checklist, --archetype, --archetype-landing, or --archetype-dashboard"
            )

        out_dir = Path(options["out_dir"]).resolve()
        force = bool(options.get("force"))
        template_package_raw = options.get("template_package")
        template_package = (
            Path(template_package_raw).resolve()
            if template_package_raw
            else None
        )
        if template_package is not None and not template_package.is_dir():
            raise CommandError(
                f"template package not found: {template_package}"
            )

        app_label_default = _resolve_app_label(contract, options.get("app_label"))
        if archetype_checklist:
            self._handle_checklist(
                contract_path,
                contract,
                out_dir,
                archetype_checklist,
                options,
                force,
                template_package,
            )
        if archetype_landing:
            self._handle_landing(
                out_dir, archetype_landing, force, app_label_default, template_package
            )
        if archetype_dashboard:
            self._handle_dashboard(
                out_dir, archetype_dashboard, force, app_label_default, template_package
            )

    def _handle_checklist(
        self,
        contract_path: Path,
        contract: dict[str, Any],
        out_dir: Path,
        archetype_value: str,
        options: dict[str, Any],
        force: bool,
        template_package: Path | None = None,
    ) -> None:
        """Handle --archetype-checklist generation."""
        mode, targets = _parse_archetype_targets(archetype_value)
        app_label_default = _resolve_app_label(contract, options.get("app_label"))
        if mode == "auto":
            archetypes = _auto_archetypes(contract, app_label_default)
            if not archetypes:
                self.stdout.write(
                    self.style.WARNING(
                        "No tables with planned_year+planned_week fields; nothing generated."
                    )
                )
                return
        else:
            archetypes = _build_archetypes(contract, app_label_default, targets)

        # Write views_auto.py (combined module).
        views_source = render_views_auto_py(archetypes)
        views_path = out_dir / "views_auto.py"
        views_written = _write_file(views_path, views_source, force=force)
        if views_written:
            self.stdout.write(self.style.SUCCESS(f"wrote {views_path}"))
        else:
            self.stdout.write(
                self.style.WARNING(f"skipped {views_path} (exists, use --force)")
            )

        # Write urls_auto.py.
        urls_source = render_urls_auto_py(archetypes)
        urls_path = out_dir / "urls_auto.py"
        urls_written = _write_file(urls_path, urls_source, force=force)
        if urls_written:
            self.stdout.write(self.style.SUCCESS(f"wrote {urls_path}"))
        else:
            self.stdout.write(
                self.style.WARNING(f"skipped {urls_path} (exists, use --force)")
            )

        # Write one template per archetype.
        for arch in archetypes:
            template_path = _template_output_path(out_dir, arch.template_path)
            default_source = render_checklist_template_html(arch)
            template_source = _resolve_template_source(
                template_package, out_dir, arch.template_path, default_source
            )
            template_written = _write_file(template_path, template_source, force=force)
            if template_written:
                self.stdout.write(self.style.SUCCESS(f"wrote {template_path}"))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"skipped {template_path} (exists, use --force)"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"generated {len(archetypes)} checklist archetype(s)"
            )
        )

    def _handle_landing(
        self,
        out_dir: Path,
        config_path_str: str,
        force: bool,
        app_label: str = "core",
        template_package: Path | None = None,
    ) -> None:
        """Handle --archetype-landing generation."""
        config_path = Path(config_path_str).resolve()
        if not config_path.is_file():
            raise CommandError(f"landing config not found: {config_path}")
        archetypes = _load_landing_config(config_path)
        if not archetypes:
            raise CommandError(
                "No landing archetypes defined in config (landings list is empty)."
            )

        # Write views_auto.py (combined module for landing views).
        views_source = render_landing_views_auto_py(
            archetypes, app_label=app_label,
        )
        views_path = out_dir / "views_auto.py"
        views_written = _write_file(views_path, views_source, force=force)
        if views_written:
            self.stdout.write(self.style.SUCCESS(f"wrote {views_path}"))
        else:
            self.stdout.write(
                self.style.WARNING(f"skipped {views_path} (exists, use --force)")
            )

        # Write urls_auto.py.
        urls_source = render_landing_urls_auto_py(archetypes)
        urls_path = out_dir / "urls_auto.py"
        urls_written = _write_file(urls_path, urls_source, force=force)
        if urls_written:
            self.stdout.write(self.style.SUCCESS(f"wrote {urls_path}"))
        else:
            self.stdout.write(
                self.style.WARNING(f"skipped {urls_path} (exists, use --force)")
            )

        # Write one template per archetype.
        for arch in archetypes:
            template_path = _template_output_path(out_dir, arch.template_path)
            default_source = render_landing_template_html(arch)
            template_source = _resolve_template_source(
                template_package, out_dir, arch.template_path, default_source
            )
            template_written = _write_file(template_path, template_source, force=force)
            if template_written:
                self.stdout.write(self.style.SUCCESS(f"wrote {template_path}"))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"skipped {template_path} (exists, use --force)"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"generated {len(archetypes)} landing archetype(s)"
            )
        )

    def _handle_dashboard(
        self,
        out_dir: Path,
        config_path_str: str,
        force: bool,
        app_label: str = "core",
        template_package: Path | None = None,
    ) -> None:
        """Handle --archetype-dashboard generation."""
        config_path = Path(config_path_str).resolve()
        if not config_path.is_file():
            raise CommandError(f"dashboard config not found: {config_path}")
        archetypes = _load_dashboard_config(config_path)
        if not archetypes:
            raise CommandError(
                "No dashboard archetypes defined in config (dashboards list is empty)."
            )

        # Write views_auto.py (combined module for dashboard views).
        views_source = render_dashboard_views_auto_py(
            archetypes, app_label=app_label,
        )
        views_path = out_dir / "views_auto.py"
        views_written = _write_file(views_path, views_source, force=force)
        if views_written:
            self.stdout.write(self.style.SUCCESS(f"wrote {views_path}"))
        else:
            self.stdout.write(
                self.style.WARNING(f"skipped {views_path} (exists, use --force)")
            )

        # Write urls_auto.py.
        urls_source = render_dashboard_urls_auto_py(archetypes)
        urls_path = out_dir / "urls_auto.py"
        urls_written = _write_file(urls_path, urls_source, force=force)
        if urls_written:
            self.stdout.write(self.style.SUCCESS(f"wrote {urls_path}"))
        else:
            self.stdout.write(
                self.style.WARNING(f"skipped {urls_path} (exists, use --force)")
            )

        # Write one template per archetype.
        for arch in archetypes:
            template_path = _template_output_path(out_dir, arch.template_path)
            default_source = render_dashboard_template_html(arch)
            template_source = _resolve_template_source(
                template_package, out_dir, arch.template_path, default_source
            )
            template_written = _write_file(template_path, template_source, force=force)
            if template_written:
                self.stdout.write(self.style.SUCCESS(f"wrote {template_path}"))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"skipped {template_path} (exists, use --force)"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"generated {len(archetypes)} dashboard archetype(s)"
            )
        )
