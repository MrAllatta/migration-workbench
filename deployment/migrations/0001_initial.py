from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ReleaseRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("space", models.CharField(max_length=128)),
                ("environment", models.CharField(max_length=32)),
                ("release_id", models.CharField(max_length=128)),
                ("git_sha", models.CharField(max_length=64)),
                ("actor", models.CharField(max_length=128)),
                ("outcome", models.CharField(max_length=32)),
                ("is_healthy", models.BooleanField(default=False)),
                ("is_rollback", models.BooleanField(default=False)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddIndex(
            model_name="releaserecord",
            index=models.Index(fields=["space", "environment", "-created_at"], name="deployment__space_3b83f5_idx"),
        ),
        migrations.AddIndex(
            model_name="releaserecord",
            index=models.Index(
                fields=["space", "environment", "is_healthy", "-created_at"],
                name="deployment__space_752230_idx",
            ),
        ),
    ]
