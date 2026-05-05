from pathlib import Path

import pytest

from importer.bundle_reader import iter_bundle_tab_rows


def test_iter_bundle_tab_rows_detects_header_with_aliases(tmp_path: Path):
    csv_path = tmp_path / "blocks.csv"
    csv_path.write_text(
        "junk,not_header\n"
        "Block Name,Type Label,Beds\n"
        "A,Field,10\n",
        encoding="utf-8",
    )
    config = {
        "required_headers": ["Block", "Block Type", "# of Beds"],
        "aliases": {
            "Block": ["Block Name"],
            "Block Type": ["Type Label"],
            "# of Beds": ["Beds"],
        },
        "column_map": {"name": "Block", "block_type": "Block Type", "num_beds": "# of Beds"},
    }

    rows = list(iter_bundle_tab_rows(str(csv_path), config))

    assert rows == [(3, {"name": "A", "block_type": "Field", "num_beds": "10"})]


def test_iter_bundle_tab_rows_applies_default_values(tmp_path: Path):
    csv_path = tmp_path / "crop_info.csv"
    csv_path.write_text(
        "Crop,Type\n"
        "Carrot,Root\n",
        encoding="utf-8",
    )
    config = {
        "required_headers": ["Crop", "Type"],
        "column_map": {"name": "Crop", "crop_type": "Type"},
        "default_values": {"seed_unit": "packet"},
    }

    rows = list(iter_bundle_tab_rows(str(csv_path), config))

    assert rows == [(2, {"name": "Carrot", "crop_type": "Root", "seed_unit": "packet"})]


def test_iter_bundle_tab_rows_raises_when_required_header_missing(tmp_path: Path):
    csv_path = tmp_path / "missing.csv"
    csv_path.write_text(
        "A,B\n"
        "x,y\n",
        encoding="utf-8",
    )
    config = {
        "required_headers": ["Crop"],
        "column_map": {"name": "Crop"},
    }

    with pytest.raises(ValueError, match="Unable to detect header row"):
        list(iter_bundle_tab_rows(str(csv_path), config))
