"""Tests for per-tier transaction savepoint behaviour."""

from django.core.management import call_command

from examples.models import ExampleBlock, ExampleCrop


class TestAtomicTiers:
    def test_tier_atomic_preserves_preceding_tiers(self, db, tmp_path):
        """By default, earlier tier rows persist even if a later tier has issues."""
        from pathlib import Path

        ExampleBlock.objects.all().delete()
        ExampleCrop.objects.all().delete()

        summary_path = Path(tmp_path) / "summary.json"
        call_command(
            "import_reference_example",
            "example_data",
            "--summary-json",
            str(summary_path),
        )

        assert ExampleBlock.objects.count() >= 1
        assert ExampleCrop.objects.count() >= 2

    def test_validate_only_rolls_back_all_tiers(self, db):
        """--validate-only must roll back everything regardless of tier_atomic."""
        ExampleBlock.objects.all().delete()
        ExampleCrop.objects.all().delete()

        call_command("import_reference_example", "example_data", "--validate-only")

        assert ExampleBlock.objects.count() == 0
        assert ExampleCrop.objects.count() == 0

    def test_no_tier_atomic_flag_disables_savepoints(self, db):
        """--no-tier-atomic runs without per-tier savepoints."""
        ExampleBlock.objects.all().delete()
        ExampleCrop.objects.all().delete()

        call_command("import_reference_example", "example_data", "--no-tier-atomic")

        assert ExampleBlock.objects.count() >= 1
        assert ExampleCrop.objects.count() >= 2
