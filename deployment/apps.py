"""Django app configuration for the deployment package."""

from django.apps import AppConfig


class DeploymentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "deployment"
