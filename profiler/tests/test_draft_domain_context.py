import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_draft_domain_context_smoke():
    out = StringIO()
    call_command("draft_domain_context", drive_tree="/dev/null", smoke=True, stdout=out)
    assert "smoke ok" in out.getvalue()


def test_draft_domain_context_basic(tmp_path):
    tree = {
        "name": "Farm Root",
        "folders": [
            {
                "name": "2025",
                "spreadsheets": [{"name": "402 Plan 2025"}],
                "folders": [],
            },
            {
                "name": "2026",
                "spreadsheets": [{"name": "402 Plan 2026"}],
                "folders": [],
            },
        ],
        "spreadsheets": [],
    }
    tree_path = tmp_path / "drive_tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    out = StringIO()
    call_command("draft_domain_context", drive_tree=str(tree_path), stdout=out)
    output = out.getvalue()
    assert "2025" in output
    assert "2026" in output
    assert "draft" in output


def test_draft_domain_context_missing_file():
    with pytest.raises(CommandError, match="not found"):
        call_command("draft_domain_context", drive_tree="/nonexistent.json")
