import json

from django.core.management import call_command


def test_snapshot_bundle_writes_manifest(tmp_path):
    source = tmp_path / "blocks.csv"
    source.write_text(
        "Block,Block Type,# of Beds,Bed Width (feet),Bedfeet per Bed\nField 1,Field,1,3,100\n",
        encoding="utf-8",
    )
    config = {
        "tabs": [
            {
                "source_csv": "blocks.csv",
                "output_path": "reference/blocks.csv",
                "required_headers": [
                    "Block",
                    "Block Type",
                    "# of Beds",
                    "Bed Width (feet)",
                    "Bedfeet per Bed",
                ],
            }
        ]
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    out_dir = tmp_path / "bundle"

    call_command("snapshot_bundle", config=str(config_path), output_dir=str(out_dir))
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "bundle-draft-1"
