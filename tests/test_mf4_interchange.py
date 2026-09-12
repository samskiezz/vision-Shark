from __future__ import annotations

import json

import numpy as np
import pytest
from asammdf import MDF, Signal
from asammdf.blocks import v4_blocks as v4b
from asammdf.blocks import v4_constants as v4c
from asammdf.blocks.source_utils import Source

from vision_shark.main import main
from vision_shark.mf4_interchange import inspect_mf4, iter_mf4_can_frames
from vision_shark.storage import RecordingStore


CAN_DTYPE = np.dtype(
    [
        ("CAN_DataFrame.BusChannel", "u1"),
        ("CAN_DataFrame.ID", "u4"),
        ("CAN_DataFrame.IDE", "u1"),
        ("CAN_DataFrame.DLC", "u1"),
        ("CAN_DataFrame.DataLength", "u1"),
        ("CAN_DataFrame.DataBytes", "u1", (64,)),
        ("CAN_DataFrame.Dir", "u1"),
        ("CAN_DataFrame.EDL", "u1"),
        ("CAN_DataFrame.BRS", "u1"),
        ("CAN_DataFrame.ESI", "u1"),
    ]
)


def _make_raw_can_mf4(path):
    samples = np.zeros(4, dtype=CAN_DTYPE)
    samples["CAN_DataFrame.BusChannel"] = [1, 1, 2, 2]
    samples["CAN_DataFrame.ID"] = [0x123, 0x123, 0x18DAF110, 0x123]
    samples["CAN_DataFrame.IDE"] = [0, 1, 1, 0]
    samples["CAN_DataFrame.DLC"] = [2, 1, 9, 4]
    samples["CAN_DataFrame.DataLength"] = [2, 1, 12, 4]
    samples["CAN_DataFrame.Dir"] = [0, 1, 0, 1]
    samples["CAN_DataFrame.EDL"] = [0, 0, 1, 0]
    samples["CAN_DataFrame.BRS"] = [0, 0, 1, 0]
    samples["CAN_DataFrame.ESI"] = [0, 0, 1, 0]
    payloads = [
        bytes.fromhex("0102"),
        bytes.fromhex("aa"),
        bytes.fromhex("00112233445566778899aabb"),
        bytes.fromhex("deadbeef"),
    ]
    for index, payload in enumerate(payloads):
        samples["CAN_DataFrame.DataBytes"][index, : len(payload)] = list(payload)

    source = Source(
        "CAN1",
        "",
        "Vision Shark MF4 fixture",
        Source.SOURCE_BUS,
        Source.BUS_TYPE_CAN,
    )
    signal = Signal(
        samples=samples,
        timestamps=np.array([0.0, 0.1, 0.2, 0.3], dtype=np.float64),
        name="CAN_DataFrame",
        source=source,
    )
    mdf = MDF(version="4.10")
    try:
        group_index = mdf.append([signal], common_timebase=True)
        group = mdf.groups[group_index]
        group.channel_group.flags |= v4c.FLAG_CG_BUS_EVENT
        group.channel_group.acq_source = v4b.SourceInformation.from_common_source(source)
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()


def _make_generic_mf4(path):
    signal = Signal(
        samples=np.array([1, 2, 3], dtype=np.uint16),
        timestamps=np.array([0.0, 0.1, 0.2]),
        name="EngineSpeed",
    )
    mdf = MDF(version="4.10")
    try:
        mdf.append([signal], common_timebase=True)
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()


def test_mf4_raw_can_inspection_and_streaming_roundtrip(tmp_path):
    source = tmp_path / "raw_can.mf4"
    _make_raw_can_mf4(source)

    info = inspect_mf4(source)
    assert info["mdf_version"].startswith("4.")
    assert info["can_bus_event_groups"] == 1
    assert info["importable_data_groups"] == 1
    assert info["importable_data_cycles"] == 4
    assert len(info["source_sha256"]) == 64
    assert "generic measurement channels are not treated as CAN frames" in info["scope"]

    frames = list(iter_mf4_can_frames(source, batch_size=2))
    assert len(frames) == 4
    assert frames[0].bus == "mf4-can-1"
    assert frames[0].arbitration_id == 0x123
    assert frames[0].data == "0102"
    assert frames[0].extended is False
    assert frames[0].direction == "rx"
    assert frames[1].arbitration_id == 0x123
    assert frames[1].extended is True
    assert frames[1].direction == "tx"
    assert frames[2].arbitration_id == 0x18DAF110
    assert frames[2].can_fd is True
    assert frames[2].brs is True
    assert frames[2].esi is True
    assert frames[2].data == "00112233445566778899aabb"
    assert frames[2].ts_ns == 200_000_000
    assert frames[3].data == "deadbeef"


def test_generic_mdf_is_not_invented_as_raw_can(tmp_path):
    source = tmp_path / "measurement.mf4"
    _make_generic_mf4(source)
    info = inspect_mf4(source)
    assert info["importable_data_groups"] == 0
    with pytest.raises(ValueError, match="generic measurement signals are not reconstructed"):
        list(iter_mf4_can_frames(source))


def test_mf4_import_frame_limit_fails_closed(tmp_path):
    source = tmp_path / "raw_can.mf4"
    _make_raw_can_mf4(source)
    with pytest.raises(ValueError, match="frame limit"):
        list(iter_mf4_can_frames(source, batch_size=2, max_frames=3))


def test_mf4_cli_inspect_and_import(tmp_path, capsys):
    source = tmp_path / "raw_can.mf4"
    data_dir = tmp_path / "data"
    _make_raw_can_mf4(source)

    assert main(["mf4-inspect", "--input", str(source)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["importable_data_cycles"] == 4

    assert (
        main(
            [
                "mf4-import-can",
                "--data-dir",
                str(data_dir),
                "--input",
                str(source),
                "--batch-size",
                "2",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["frames"] == 4

    store = RecordingStore(data_dir)
    try:
        rows = store.list_recordings()
        assert len(rows) == 1
        recording = rows[0]
        assert recording["frame_count"] == 4
        assert recording["metadata"]["source_sha256"] == result["source_sha256"]
        restored = store.load_frames(recording["id"])
        assert restored[2].can_fd is True
        assert restored[2].data == "00112233445566778899aabb"
    finally:
        store.close()


def test_non_mdf_file_rejected_before_parser(tmp_path):
    source = tmp_path / "fake.mf4"
    source.write_bytes(b"not-an-mdf")
    with pytest.raises(ValueError, match="MDF file identifier"):
        inspect_mf4(source)
