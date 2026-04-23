import pytest

from examples.models import ExampleCrop
from importer.lookups import resolve_fk_by_text


@pytest.mark.django_db
def test_resolve_fk_by_text_exact_and_normalized():
    ExampleCrop.objects.create(name="Lettuce Mix")
    cache = {}

    class _Style:
        @staticmethod
        def WARNING(value):
            return value

    class _Stdout:
        @staticmethod
        def write(_):
            return None

    exact = resolve_fk_by_text(
        ExampleCrop, "name", "Lettuce Mix", "crop", cache, _Stdout(), _Style, write_disabled=False
    )
    normalized = resolve_fk_by_text(
        ExampleCrop, "name", "  lettuce   mix ", "crop", cache, _Stdout(), _Style, write_disabled=False
    )
    assert exact.id == normalized.id
