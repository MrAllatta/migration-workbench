"""Tests for stub_writer.py."""

from workbook.codegen.stub_writer import ensure_stub, MARKER


def test_stub_creates_new_file(tmp_path):
    stub = ensure_stub(tmp_path / "models.py", "models_auto")
    assert stub.exists()
    content = stub.read_text()
    assert "from .models_auto import *" in content
    assert MARKER in content


def test_stub_preserves_custom_code(tmp_path):
    stub = tmp_path / "models.py"
    stub.write_text(
        "from .old import *\n\n# --- custom models below this line ---\n\nclass FarmUser:\n    pass\n"
    )
    ensure_stub(stub, "models_auto")
    content = stub.read_text()
    assert "class FarmUser:" in content
    assert "from .models_auto import *" in content


def test_stub_updates_import_line(tmp_path):
    stub = tmp_path / "models.py"
    stub.write_text(
        "from .old_module import *\n\n# --- custom models below this line ---\nclass Custom: pass\n"
    )
    ensure_stub(stub, "models_auto")
    content = stub.read_text()
    assert "from .models_auto import *" in content
    assert "from .old_module import *" not in content
    assert "class Custom: pass" in content


def test_stub_handles_no_marker(tmp_path):
    stub = tmp_path / "models.py"
    stub.write_text("from .old_module import *")
    ensure_stub(stub, "models_auto")
    content = stub.read_text()
    assert MARKER in content
