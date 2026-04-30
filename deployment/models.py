from django.db import models


class ReleaseRecord(models.Model):
    space = models.CharField(max_length=128)
    environment = models.CharField(max_length=32)
    release_id = models.CharField(max_length=128)
    git_sha = models.CharField(max_length=64)
    actor = models.CharField(max_length=128)
    outcome = models.CharField(max_length=32)
    is_healthy = models.BooleanField(default=False)
    is_rollback = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["space", "environment", "-created_at"]),
            models.Index(fields=["space", "environment", "is_healthy", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.space}:{self.environment}:{self.release_id}:{self.outcome}"
