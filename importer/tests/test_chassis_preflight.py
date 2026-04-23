from django.core.management import call_command

from examples.models import ExampleBlock, ExampleCrop


def test_validate_only_rolls_back(db):
    call_command("import_reference_example", "example_data", "--validate-only")
    assert ExampleBlock.objects.count() == 0
    assert ExampleCrop.objects.count() == 0
