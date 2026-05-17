"""Django app configuration for the profiler package."""
from django.apps import AppConfig


class ProfilerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "profiler"
