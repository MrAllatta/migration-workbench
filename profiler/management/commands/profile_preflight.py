"""Validate profiling auth/runtime prerequisites (credentials + optional folder access)."""

from __future__ import annotations

import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from profiler.management.commands._config_helpers import load_folder_id_from_config
from connectors.google_sheets import (
    DRIVE_READONLY_SCOPE,
    SHEETS_READONLY_SCOPE,
    build_google_service,
    extract_drive_folder_id,
)


class Command(BaseCommand):
    """Validate profiling auth/runtime prerequisites (credentials + optional folder access)."""

    help = "Validate profiling auth/runtime prerequisites (credentials + optional folder access)."

    def add_arguments(self, parser):
        """Add command-line arguments for profile_preflight."""
        parser.add_argument(
            "--folder", help="Drive folder id or URL to validate read access"
        )
        parser.add_argument(
            "--config",
            default=None,
            help="Cohort corpus JSON config path; uses folder_id when --folder is omitted",
        )
        parser.add_argument(
            "--smoke",
            action="store_true",
            help="Run local-only checks without network calls",
        )

    def handle(self, *args, **options):
        """Execute the preflight check. Verifies Google Sheets/Drive credentials and optionally tests folder access."""
        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("profile_preflight smoke ok"))
            return

        credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if credentials_path:
            path = Path(credentials_path).expanduser()
            if path.exists():
                self.stdout.write(f"credentials path exists: {path}")
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"GOOGLE_APPLICATION_CREDENTIALS points to non-existent path: {path}; "
                        "relying on ADC/default credentials"
                    )
                )
        else:
            self.stdout.write(
                "GOOGLE_APPLICATION_CREDENTIALS not set; relying on ADC/default credentials"
            )

        scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
        drive_service = build_google_service("drive", "v3", scopes)
        sheets_service = build_google_service("sheets", "v4", scopes)
        self.stdout.write("drive/sheets clients initialized")

        folder = options.get("folder") or load_folder_id_from_config(
            options.get("config")
        )
        if folder:
            folder_id = extract_drive_folder_id(folder)
            meta = (
                drive_service.files()
                .get(
                    fileId=folder_id, fields="id,name,mimeType", supportsAllDrives=True
                )
                .execute()
            )
            self.stdout.write(f"folder readable: {meta.get('name')} ({meta.get('id')})")

        drive_service.about().get(fields="user").execute()
        _ = sheets_service
        self.stdout.write(self.style.SUCCESS("profile_preflight ok"))
