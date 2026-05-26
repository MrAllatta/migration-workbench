from pathlib import Path
import yaml
from workbook.partial_output import PartialOutputCollector


def test_collector_add_and_summary():
    collector = PartialOutputCollector()
    collector.add(
        {"bundle_worksheet_title": "Irrigation", "workbook_code": "504"},
        check_id="SCAFFOLD_PIVOT_TABLE",
        message="Numeric headers detected",
        action="Exclude from corpus config",
    )
    assert not collector.is_empty()
    summary = collector.summary()
    assert "SCAFFOLD_PARTIAL_OUTPUT" in summary
    assert "Irrigation" in summary


def test_write_rejection_file(tmp_path: Path):
    collector = PartialOutputCollector()
    collector.add(
        {"bundle_worksheet_title": "Irrigation", "workbook_code": "504"},
        check_id="SCAFFOLD_PIVOT_TABLE",
        message="Numeric headers",
    )
    rejection_path = tmp_path / "rejected.yaml"
    collector.write_rejection_file(rejection_path)
    payload = yaml.safe_load(rejection_path.read_text(encoding="utf-8"))
    assert len(payload["rejected_tables"]) == 1
    assert payload["rejected_tables"][0]["error"]["check_id"] == "SCAFFOLD_PIVOT_TABLE"
