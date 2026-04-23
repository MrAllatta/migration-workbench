from django.core.management import call_command

from examples.models import ExampleBlock, ExampleCrop


def test_import_reference_example_apply(db, tmp_path):
    summary = tmp_path / "summary.json"
    call_command("import_reference_example", "example_data", "--summary-json", str(summary))
    assert ExampleBlock.objects.count() == 1
    assert ExampleCrop.objects.count() == 2
    assert summary.exists()
