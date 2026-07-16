"""Generate command group ("wb generate ...").

Extracted from deployment/wb_cli as part of e03s04
(cli-router-split). Owns:

- ``_generate_models`` — generate Django models.py
- ``_generate_admin`` — generate Django admin.py
- ``_generate_import`` — generate Django import command
- ``_generate_manifest`` — generate view manifest
- ``_generate_views`` — generate Django views, templates, URLs
- ``build_generate_parser`` — wire the ``generate`` subparser
"""

from __future__ import annotations

import argparse
from typing import Any


def _generate_models(args: argparse.Namespace) -> int:
    from deployment.wb_cli import _setup_django  # noqa: PLC0415

    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs = {
        "contract": args.contract,
        "out": args.out,
        "app_label": args.app_label,
        "force": args.force,
        "diff": args.diff,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command("generate_models", **kwargs)
    return 0

def _generate_admin(args: argparse.Namespace) -> int:
    from deployment.wb_cli import _setup_django  # noqa: PLC0415

    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs = {
        "contract": args.contract,
        "manifest": args.manifest,
        "codegen_manifest": getattr(args, "codegen_manifest", None),
        "out": args.out,
        "app_label": args.app_label,
        "force": args.force,
        "diff": args.diff,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command("generate_admin", **kwargs)
    return 0

def _generate_import(args: argparse.Namespace) -> int:
    from deployment.wb_cli import _setup_django  # noqa: PLC0415

    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs = {
        "contract": args.contract,
        "out": args.out,
        "app_label": args.app_label,
        "force": args.force,
        "diff": args.diff,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command("generate_import", **kwargs)
    return 0

def _generate_manifest(args: argparse.Namespace) -> int:
    from deployment.wb_cli import _setup_django  # noqa: PLC0415

    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs = {
        "structure": args.structure,
        "out": args.out,
    }
    if args.contract:
        kwargs["schema_contract"] = args.contract
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    call_command("scaffold_view_manifest", **kwargs)
    return 0

def _generate_views(args: argparse.Namespace) -> int:
    from deployment.wb_cli import _setup_django  # noqa: PLC0415

    _setup_django(getattr(args, "django_settings", None))
    from django.core.management import call_command

    kwargs: dict[str, Any] = {
        "contract": args.contract,
        "out_dir": args.out_dir,
    }
    if getattr(args, "app_label", None):
        kwargs["app_label"] = args.app_label
    if getattr(args, "archetype_checklist", None):
        kwargs["archetype_checklist"] = args.archetype_checklist
    if getattr(args, "archetype_landing", None):
        kwargs["archetype_landing"] = args.archetype_landing
    if getattr(args, "archetype_dashboard", None):
        kwargs["archetype_dashboard"] = args.archetype_dashboard
    if getattr(args, "template_package", None):
        kwargs["template_package"] = args.template_package
    if getattr(args, "force", None):
        kwargs["force"] = args.force
    if getattr(args, "validate", None):
        kwargs["validate"] = args.validate
    call_command("generate_views", **kwargs)
    return 0

def build_generate_parser(sub: argparse._SubParsersAction) -> None:
    """Add 'generate {models,admin,import,manifest}' subcommands to *sub*."""
    gen_cmd = sub.add_parser("generate", help="Generate code from a schema contract")
    gen_sub = gen_cmd.add_subparsers(dest="generate_command", required=True)

    models_cmd = gen_sub.add_parser("models", help="Generate Django models.py")
    models_cmd.add_argument("--contract", required=True)
    models_cmd.add_argument("--out", default=None)
    models_cmd.add_argument("--app-label", default=None)
    models_cmd.add_argument("--force", action="store_true")
    models_cmd.add_argument("--diff", action="store_true")
    models_cmd.add_argument("--django-settings", default=None)
    models_cmd.set_defaults(func=_generate_models)

    admin_cmd = gen_sub.add_parser("admin", help="Generate Django admin.py")
    admin_cmd.add_argument("--contract", required=True)
    admin_cmd.add_argument("--manifest", default=None)
    admin_cmd.add_argument("--codegen-manifest", default=None)
    admin_cmd.add_argument("--out", default=None)
    admin_cmd.add_argument("--app-label", default=None)
    admin_cmd.add_argument("--force", action="store_true")
    admin_cmd.add_argument("--diff", action="store_true")
    admin_cmd.add_argument("--django-settings", default=None)
    admin_cmd.set_defaults(func=_generate_admin)

    import_cmd = gen_sub.add_parser("import", help="Generate Django import command")
    import_cmd.add_argument("--contract", required=True)
    import_cmd.add_argument("--out", default=None)
    import_cmd.add_argument("--app-label", default=None)
    import_cmd.add_argument("--force", action="store_true")
    import_cmd.add_argument("--diff", action="store_true")
    import_cmd.add_argument("--django-settings", default=None)
    import_cmd.set_defaults(func=_generate_import)

    manifest_cmd = gen_sub.add_parser("manifest", help="Generate view manifest")
    manifest_cmd.add_argument("--contract", required=True)
    manifest_cmd.add_argument("--out", default=None)
    manifest_cmd.add_argument("--structure", default=None)
    manifest_cmd.add_argument("--django-settings", default=None)
    manifest_cmd.set_defaults(func=_generate_manifest)

    views_cmd = gen_sub.add_parser("views", help="Generate Django views, templates, and URLs")
    views_cmd.add_argument("--contract", required=True)
    views_cmd.add_argument("--out-dir", required=True)
    views_cmd.add_argument("--app-label", default=None)
    views_cmd.add_argument("--archetype-checklist", default=None)
    views_cmd.add_argument("--archetype-landing", default=None)
    views_cmd.add_argument("--archetype-dashboard", default=None)
    views_cmd.add_argument("--template-package", default=None)
    views_cmd.add_argument("--force", action="store_true")
    views_cmd.add_argument("--validate", action="store_true")
    views_cmd.add_argument("--django-settings", default=None)
    views_cmd.set_defaults(func=_generate_views)

