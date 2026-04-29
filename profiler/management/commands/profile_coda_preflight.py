from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from connectors.coda_source import (
    build_coda_session,
    get_doc,
    get_whoami,
    resolve_doc_id,
)


class Command(BaseCommand):
    help = "Validate Coda API token and optional doc access (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--doc",
            "--doc-url",
            dest="doc",
            help="Optional Coda doc URL or id to verify readability",
        )
        parser.add_argument(
            "--smoke",
            action="store_true",
            help="Run local-only checks without network calls",
        )

    def handle(self, *args, **options):
        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("profile_coda_preflight smoke ok"))
            return

        token = os.environ.get("CODA_API_TOKEN")
        if not token or not str(token).strip():
            raise CommandError("CODA_API_TOKEN is not set or is empty")

        session = build_coda_session()
        try:
            who = get_whoami(session)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Coda API whoami failed: {exc}") from exc

        name = who.get("name") or who.get("loginId") or who.get("id")
        self.stdout.write(f"Coda API ok (whoami): {name}")

        doc_value = options.get("doc")
        if doc_value:
            doc_id = resolve_doc_id(session, doc_value)
            if not doc_id:
                raise CommandError(f"Could not resolve Coda doc id from {doc_value!r}")
            try:
                meta = get_doc(session, doc_id)
            except Exception as exc:  # noqa: BLE001
                raise CommandError(f"Could not read doc {doc_id}: {exc}") from exc
            self.stdout.write(f"Doc readable: {meta.get('name') or doc_id} ({doc_id})")

        self.stdout.write(self.style.SUCCESS("profile_coda_preflight ok"))
