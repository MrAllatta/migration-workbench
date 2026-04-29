import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command


def test_profile_coda_doc_smoke():
    out = StringIO()
    call_command("profile_coda_doc", smoke=True, stdout=out)
    assert "smoke ok" in out.getvalue()


def test_profile_coda_table_smoke():
    out = StringIO()
    call_command("profile_coda_table", smoke=True, stdout=out)
    assert "smoke ok" in out.getvalue()


def test_scan_coda_formula_columns_smoke_writes_output(tmp_path):
    config = {
        "workbooks": [{"name": "Doc 1", "doc_url": "https://coda.io/d/X_dDocId"}],
        "patterns": [{"name": "filter", "regex": r"Filter\("}],
    }
    config_path = tmp_path / "scan_coda.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    out_path = tmp_path / "out.json"

    call_command("scan_coda_formula_columns", config=str(config_path), out=str(out_path), smoke=True)

    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["mode"] == "smoke"
    assert result["pattern_count"] == 1
    assert result["workbooks"] == ["Doc 1"]


def test_profile_coda_preflight_smoke():
    out = StringIO()
    call_command("profile_coda_preflight", smoke=True, stdout=out)
    assert "smoke ok" in out.getvalue()


def test_profile_coda_corpus_smoke_writes_artifacts(tmp_path):
    config = {
        "docs": [
            {"name": "Doc A", "doc_url": "https://coda.io/d/X_dDocId"},
            {"name": "Doc B", "doc_url": "https://coda.io/d/Y_dDocId"},
        ],
        "table_auto_limit": 5,
    }
    config_path = tmp_path / "coda_corpus.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    out_dir = tmp_path / "out"
    date_stamp = "2026-04-29"

    call_command(
        "profile_coda_corpus",
        config=str(config_path),
        out_dir=str(out_dir),
        date_stamp=date_stamp,
        smoke=True,
    )

    discovery = out_dir / f"coda_discovery_{date_stamp}.json"
    index = out_dir / f"coda_table_index_{date_stamp}.json"
    assert discovery.exists()
    assert index.exists()
    d = json.loads(discovery.read_text(encoding="utf-8"))
    idx = json.loads(index.read_text(encoding="utf-8"))
    assert d["mode"] == "smoke"
    assert idx["mode"] == "smoke"
    assert idx["base_tables"] == []
    assert idx["views"] == []


def test_profile_coda_table_lists_tables(monkeypatch):
    monkeypatch.setenv("CODA_API_TOKEN", "test-token")
    fake_tables = [
        {"id": "t1", "name": "Alpha", "type": "table", "rowCount": 3},
        {"id": "t2", "name": "Beta", "type": "view", "rowCount": 1},
    ]

    with patch("profiler.management.commands.profile_coda_table.list_tables", return_value=fake_tables):
        out = StringIO()
        call_command("profile_coda_table", doc="https://coda.io/d/S_d1", stdout=out)

    text = out.getvalue()
    assert "Alpha" in text
    assert "Beta" in text
