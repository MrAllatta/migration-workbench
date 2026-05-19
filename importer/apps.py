"""Django app configuration for the importer package."""

from django.apps import AppConfig


class ImporterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "importer"
