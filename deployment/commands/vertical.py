"""Vertical command group ("wb vertical ...").

Extracted from deployment/wb_cli as part of e03s04
(cli-router-split). Owns:

- ``_vertical_list`` — list available vertical templates
- ``_vertical_show`` — show details of a vertical template
- ``build_vertical_parser`` — wire the ``vertical`` subparser
"""

from __future__ import annotations

import argparse


from workbook.tools.vertical_registry import discover_verticals, load_vertical
def _vertical_list(args: argparse.Namespace) -> int:
    """List available vertical templates."""
    from deployment.wb_cli import ERROR_CODES, _render_output  # noqa: PLC0415

    try:
        verticals = discover_verticals()
        if args.json:
            return _render_output(
                {
                    "ok": True,
                    "error_code": None,
                    "message": f"Found {len(verticals)} vertical(s).",
                    "verticals": verticals,
                },
                args.json,
            )

        if not verticals:
            print("No vertical templates found.")
            return 0

        # Print table header
        print(f"{'Name':<15} {'Version':<10} {'Confidence':<12} {'Description'}")
        print("-" * 80)
        for v in verticals:
            name = v.get("name", "")
            version = v.get("version", "")
            confidence = v.get("confidence", "")
            description = v.get("description", "")
            # Truncate description if too long
            if len(description) > 50:
                description = description[:47] + "..."
            print(f"{name:<15} {version:<10} {confidence:<12} {description}")
        return 0
    except Exception as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": str(exc),
            },
            args.json,
        )

def _vertical_show(args: argparse.Namespace) -> int:
    """Show details of a vertical template."""
    from deployment.wb_cli import ERROR_CODES, _render_output  # noqa: PLC0415

    try:
        vertical = load_vertical(args.name)
        if args.json:
            # Convert VerticalTemplate to dict for JSON output
            from dataclasses import asdict

            return _render_output(
                {
                    "ok": True,
                    "error_code": None,
                    "message": f"Vertical '{args.name}' details.",
                    "vertical": asdict(vertical),
                },
                args.json,
            )

        # Pretty print vertical details
        print(f"Name: {vertical.name}")
        print(f"Version: {vertical.version}")
        print(f"Description: {vertical.description}")
        print(f"Confidence: {vertical.confidence}")

        if vertical.domain_context:
            print("\nDomain Context:")
            if vertical.domain_context.get("vocabulary"):
                print("  Vocabulary:")
                for category, terms in vertical.domain_context["vocabulary"].items():
                    print(f"    {category}: {', '.join(terms)}")
            if vertical.domain_context.get("glossary"):
                print("  Glossary:")
                for term, definition in vertical.domain_context["glossary"].items():
                    print(f"    {term}: {definition}")
            if vertical.domain_context.get("entities"):
                print("  Entities:")
                for entity in vertical.domain_context["entities"]:
                    print(
                        f"    - {entity.get('name', 'Unknown')}: {entity.get('description', '')}"
                    )

        if vertical.entity_templates:
            print("\nEntity Templates:")
            for entity_name, template in vertical.entity_templates.items():
                print(f"  {entity_name}:")
                if template.get("model_meta"):
                    meta = template["model_meta"]
                    if meta.get("verbose_name"):
                        print(f"    verbose_name: {meta['verbose_name']}")
                    if meta.get("verbose_name_plural"):
                        print(f"    verbose_name_plural: {meta['verbose_name_plural']}")
                    if meta.get("ordering"):
                        print(f"    ordering: {meta['ordering']}")
                if template.get("columns"):
                    print(f"    Columns ({len(template['columns'])}):")
                    for col in template["columns"]:
                        col_name = col.get("name", "unknown")
                        data_type = col.get("data_type", "unknown")
                        nullable = "NULL" if col.get("null", True) else "NOT NULL"
                        print(f"      - {col_name} ({data_type}, {nullable})")
                if template.get("admin"):
                    admin = template["admin"]
                    if admin.get("list_display"):
                        print(f"    list_display: {admin['list_display']}")
                    if admin.get("search_fields"):
                        print(f"    search_fields: {admin['search_fields']}")
                    if admin.get("list_filter"):
                        print(f"    list_filter: {admin['list_filter']}")
                if template.get("import_config"):
                    import_config = template["import_config"]
                    if import_config.get("unique_on"):
                        print(f"    unique_on: {import_config['unique_on']}")
                    if import_config.get("fk_lookup"):
                        print(f"    fk_lookup: {import_config['fk_lookup']}")

        if vertical.interaction_defaults:
            print("\nInteraction Defaults:")
            if vertical.interaction_defaults.get("roles"):
                print("  Roles:")
                for role, config in vertical.interaction_defaults["roles"].items():
                    print(f"    {role}:")
                    print(f"      archetype: {config.get('archetype', 'unknown')}")
                    print(f"      tabs: {config.get('tabs', [])}")

        if vertical.signal_thresholds:
            print("\nSignal Thresholds:")
            for key, value in vertical.signal_thresholds.items():
                print(f"  {key}: {value}")

        return 0
    except FileNotFoundError:
        return _render_output(
            {
                "ok": False,
                "error_code": "WB-VERTICAL-4001",
                "message": f"Vertical template '{args.name}' not found.",
            },
            args.json,
        )
    except Exception as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": str(exc),
            },
            args.json,
        )


def build_vertical_parser(sub: argparse._SubParsersAction) -> None:
    """Wire the ``vertical`` subparser into *sub*."""
    vert_cmd = sub.add_parser(
        "vertical", help="Vertical template operations"
    )
    vert_sub = vert_cmd.add_subparsers(
        dest="vertical_command", required=True
    )

    list_cmd = vert_sub.add_parser("list", help="List vertical templates")
    list_cmd.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    list_cmd.set_defaults(func=_vertical_list)

    show_cmd = vert_sub.add_parser(
        "show", help="Show details of a vertical template"
    )
    show_cmd.add_argument("--json", action="store_true", help="Output as JSON")
    show_cmd.add_argument("name", help="Vertical template name")
    show_cmd.set_defaults(func=_vertical_show)
