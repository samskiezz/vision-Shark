from __future__ import annotations

import canmatrix.formats as formats
import pytest

from vision_shark.database_interchange import (
    SUPPORTED_DATABASE_FORMATS,
    convert_to_dbc,
    inspect_database,
)
from vision_shark.dbc import parse_database
from vision_shark.main import main


DBC = '''VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 291 VehicleStatus: 8 ECU
 SG_ Speed : 0|16@1+ (0.1,0) [0|6553.5] "km/h" ECU
 SG_ Temperature : 16|8@1- (1,-40) [-40|215] "C" ECU
'''


def _source_cluster():
    cluster = formats.loads(DBC.encode("utf-8"), import_type="dbc")
    assert cluster
    return cluster


def _write_exportable_format(path, fmt: str):
    cluster = _source_cluster()
    capabilities = formats.supportedFormats[fmt]
    assert "load" in capabilities
    assert "dump" in capabilities
    with path.open("wb") as target:
        if "clusterExporter" in capabilities:
            formats.dump(cluster, target, fmt)
        else:
            formats.dump(next(iter(cluster.values())), target, fmt)
    assert path.stat().st_size > 0


def test_supported_database_readers_are_loaded():
    assert SUPPORTED_DATABASE_FORMATS == {"dbc", "arxml", "kcd", "sym", "fibex"}
    for fmt in SUPPORTED_DATABASE_FORMATS:
        assert fmt in formats.supportedFormats
        assert "load" in formats.supportedFormats[fmt]


def test_dbc_inspection_and_conversion_is_evidence_bound(tmp_path):
    source = tmp_path / "source.dbc"
    source.write_text(DBC)
    inspected = inspect_database(source, "dbc")

    assert inspected["matrix_count"] == 1
    assert inspected["frame_count"] == 1
    assert inspected["signal_count"] == 2
    assert inspected["runtime_compatible"] is True
    assert len(inspected["source_sha256"]) == 64
    assert "no vehicle transmit authority" in inspected["scope"]

    result = convert_to_dbc(source, "dbc", tmp_path / "out")
    assert result["all_core_semantics_preserved"] is True
    assert result["all_runtime_dbc_validated"] is True
    assert len(result["outputs"]) == 1
    output = result["outputs"][0]
    assert output["core_semantics_preserved"] is True
    assert output["runtime_dbc_validated"] is True
    generated = parse_database((tmp_path / "out" / "matrix_1.dbc").read_text())
    assert generated["signal_count"] == 2


@pytest.mark.parametrize("fmt", ["kcd", "sym", "arxml"])
def test_exportable_reviewed_formats_normalize_to_dbc(tmp_path, fmt):
    source = tmp_path / f"source.{fmt}"
    _write_exportable_format(source, fmt)

    inspected = inspect_database(source, fmt)
    assert inspected["frame_count"] >= 1
    assert inspected["signal_count"] >= 2

    result = convert_to_dbc(source, fmt, tmp_path / f"out-{fmt}")
    assert result["matrix_count"] >= 1
    assert all(item["bytes"] > 0 for item in result["outputs"])
    assert all(len(item["sha256"]) == 64 for item in result["outputs"])
    assert all(item["runtime_dbc_validated"] for item in result["outputs"])


def test_fibex_path_is_real_reader_even_if_exporter_is_not_available(tmp_path):
    assert "load" in formats.supportedFormats["fibex"]
    if "dump" not in formats.supportedFormats["fibex"]:
        return
    source = tmp_path / "source.xml"
    _write_exportable_format(source, "fibex")
    result = convert_to_dbc(source, "fibex", tmp_path / "out-fibex")
    assert result["matrix_count"] >= 1
    assert all(item["runtime_dbc_validated"] for item in result["outputs"])


def test_xml_entity_and_ambiguous_xml_are_rejected_before_parser(tmp_path):
    source = tmp_path / "unsafe.xml"
    source.write_text('<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')
    with pytest.raises(ValueError, match="DTD/entity"):
        inspect_database(source, "fibex")
    with pytest.raises(ValueError, match="ambiguous"):
        inspect_database(source, "xml")


def test_cli_inspect_and_convert(tmp_path, capsys):
    source = tmp_path / "source.dbc"
    output_dir = tmp_path / "converted"
    source.write_text(DBC)

    assert main(["db-inspect", "--input", str(source), "--format", "dbc"]) == 0
    inspected = capsys.readouterr().out
    assert '"signal_count": 2' in inspected

    assert (
        main(
            [
                "db-convert",
                "--input",
                str(source),
                "--format",
                "dbc",
                "--to",
                "dbc",
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    converted = capsys.readouterr().out
    assert '"all_core_semantics_preserved": true' in converted
    assert list(output_dir.glob("*.dbc"))
