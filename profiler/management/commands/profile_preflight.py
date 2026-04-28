from __future__ import annotations

import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from connectors.google_sheets import DRIVE_READONLY_SCOPE, SHEETS_READONLY_SCOPE, build_google_service, extract_drive_folder_id


class Command(BaseCommand):
    help = "Validate profiling auth/runtime prerequisites (credentials + optional folder access)."

    def add_arguments(self, parser):
        parser.add_argument("--folder", help="Drive folder id or URL to validate read access")
        parser.add_argument("--smoke", action="store_true", help="Run local-only checks without network calls")

    def handle(self, *args, **options):
        credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if credentials_path:
            path = Path(credentials_path).expanduser()
            if not path.exists():
                raise CommandError(f"GOOGLE_APPLICATION_CREDENTIALS path does not exist: {path}")
            self.stdout.write(f"credentials path exists: {path}")
        else:
            self.stdout.write("GOOGLE_APPLICATION_CREDENTIALS not set; relying on ADC/default credentials")

        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("profile_preflight smoke ok"))
            return

        scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
        drive_service = build_google_service("drive", "v3", scopes)
        sheets_service = build_google_service("sheets", "v4", scopes)
        self.stdout.write("drive/sheets clients initialized")

        folder = options.get("folder")
        if folder:
            folder_id = extract_drive_folder_id(folder)
            meta = (
                drive_service.files()
                .get(fileId=folder_id, fields="id,name,mimeType", supportsAllDrives=True)
                .execute()
            )
            self.stdout.write(f"folder readable: {meta.get('name')} ({meta.get('id')})")

        drive_service.about().get(fields="user").execute()
        _ = sheets_service
        self.stdout.write(self.style.SUCCESS("profile_preflight ok"))

