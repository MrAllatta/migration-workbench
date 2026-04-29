from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.coda_source import build_coda_session, get_doc, resolve_doc_id
from profiler.tools.coda_corpus import build_canvas_artifact_for_doc, write_json


class Command(BaseCommand):
    help = "Extract plain text from Coda canvas pages (content API) or optional markdown export."

    def add_arguments(self, parser):
        parser.add_argument(
            "--doc",
            "--doc-url",
            dest="doc",
            help="Coda doc URL or raw doc id",
        )
        parser.add_argument("--out", default=None, help="Output JSON path")
        parser.add_argument(
            "--max-pages", type=int, default=50, help="Max pages to fetch"
        )
        parser.add_argument(
            "--max-chars-per-page",
            type=int,
            default=50_000,
            help="Truncate each page body after this many characters",
        )
        parser.add_argument(
            "--max-content-items",
            type=int,
            default=5000,
            help="Max content elements per page when using plain API (not export)",
        )
        parser.add_argument(
            "--use-export",
            action="store_true",
            help="Use async markdown export per page instead of plain text content API",
        )
        parser.add_argument(
            "--smoke", action="store_true", help="Run without network calls"
        )

    def handle(self, *args, **options):
        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("profile_coda_canvas smoke ok"))
            return

        doc_value = options.get("doc")
        if not doc_value:
            raise CommandError("--doc is required unless --smoke is used")
        out = options.get("out")
        if not out:
            raise CommandError("--out is required unless --smoke is used")

        session = build_coda_session()
        doc_id = resolve_doc_id(session, doc_value)
        if not doc_id:
            raise CommandError(f"Could not resolve Coda doc id from {doc_value!r}")

        doc_meta = get_doc(session, doc_id)
        title = str(doc_meta.get("name") or doc_id)

        canvas_cfg = {
            "enabled": True,
            "max_pages": int(options["max_pages"]),
            "max_chars_per_page": int(options["max_chars_per_page"]),
            "max_content_items": int(options["max_content_items"]),
            "use_export": bool(options["use_export"]),
        }
        payload = build_canvas_artifact_for_doc(session, title, doc_id, canvas_cfg)

        out_path = Path(out).resolve()
        stamp = datetime.now(UTC).date().isoformat()
        write_json(
            out_path,
            {
                "generated_at": stamp,
                "docs": [payload],
            },
        )
        page_count = len(payload.get("pages") or [])
        self.stdout.write(self.style.SUCCESS(f"wrote {out_path} ({page_count} pages)"))
