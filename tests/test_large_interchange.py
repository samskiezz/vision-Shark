from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vision_shark.domain import Frame
from vision_shark.large_interchange import iter_parquet, parquet_info, write_parquet
from vision_shark.main import main
from vision_shark.storage import RecordingStore


def frame(
    ts: int,
    arbitration_id: int,
    data: str,
    *,
    bus: str = "can0",
    extended: bool = False,
    can_fd: bool = False,
    brs: bool = False,
    esi: bool = False,
    rtr: bool = False,
    error: bool = False,
    direction: str = "rx",
) -> Frame:
    return Frame(
        ts_ns=ts,
        bus=bus,
        arbitration_id=arbitration_id,
        data=data,
        extended=extended,
        can_fd=can_fd,
        brs=brs,
        esi=esi,
        rtr=rtr,
        error=error,
        direction=direction,
    )


def test_parquet_roundtrip_preserves_frame_semantics(tmp_path):
    original = [
        frame(1, 0x123, "0102"),
        frame(
            2,
            0x18DAF110,
            "00112233445566778899aabb",
            bus="can1",
            extended=True,
            can_fd=True,
            brs=True,
            esi=True,
            direction="unknown",
        ),
        frame(3, 0x321, "", rtr=True),
        frame(4, 0x456, "deadbeef", error=True, direction="tx"),
    ]
    path = tmp_path / "capture.parquet"
    result = write_parquet(original, path, row_group_size=2)
    restored = list(iter_parquet(path, batch_size=1))

    assert [item.model_dump() for item in restored] == [
        item.model_dump() for item in original
    ]
    assert result["rows"] == 4
    assert result["row_groups"] == 2
    assert len(result["sha256"]) == 64
    assert parquet_info(path)["format"] == "frames-v1"


def test_parquet_streams_multiple_row_groups(tmp_path):
    path = tmp_path / "many.parquet"
    frames = [frame(index, 0x100 + index, f"{index:02x}") for index in range(7)]
    result = write_parquet(iter(frames), path, row_group_size=3)

    assert result["row_groups"] == 3
    assert [item.arbitration_id for item in iter_parquet(path, batch_size=2)] == [
        item.arbitration_id for item in frames
    ]


def test_parquet_rejects_untrusted_generic_schema(tmp_path):
    path = tmp_path / "generic.parquet"
    pq.write_table(pa.table({"value": [1, 2, 3]}), path)

    with pytest.raises(ValueError, match="not a Vision Shark"):
        list(iter_parquet(path))


def test_parquet_rejects_timestamp_outside_int64(tmp_path):
    path = tmp_path / "bad.parquet"
    oversized = frame(9_223_372_036_854_775_808, 0x123, "00")

    with pytest.raises(ValueError, match="timestamp exceeds"):
        write_parquet([oversized], path)
    assert not path.exists()


def test_recording_store_streaming_append_and_read(tmp_path):
    store = RecordingStore(tmp_path)
    try:
        recording_id = store.start_recording("test", "can0")
        expected = [frame(index, 0x200, f"{index % 256:02x}") for index in range(25)]
        assert store.append_frames_streaming(recording_id, iter(expected), batch_size=4) == 25
        store.stop_recording(recording_id, {"capture_complete": True})
        actual = list(store.iter_frames(recording_id, batch_size=3))
        assert [item.model_dump() for item in actual] == [
            item.model_dump() for item in expected
        ]
    finally:
        store.close()


def test_cli_parquet_export_import_roundtrip(tmp_path, capsys):
    source_dir = tmp_path / "source"
    destination_dir = tmp_path / "destination"
    capture = tmp_path / "capture.parquet"
    store = RecordingStore(source_dir)
    try:
        recording_id = store.start_recording("test", "can0")
        expected = [
            frame(10, 0x123, "01020304"),
            frame(
                20,
                0x18DAF110,
                "00112233445566778899aabbccddeeff",
                extended=True,
                can_fd=True,
                brs=True,
            ),
        ]
        store.append_frames(recording_id, expected)
        store.stop_recording(recording_id, {"capture_complete": True})
    finally:
        store.close()

    assert (
        main(
            [
                "parquet-export",
                "--data-dir",
                str(source_dir),
                "--recording-id",
                str(recording_id),
                "--output",
                str(capture),
                "--row-group-size",
                "1",
            ]
        )
        == 0
    )
    assert capture.exists()
    capsys.readouterr()

    assert (
        main(
            [
                "parquet-import",
                "--data-dir",
                str(destination_dir),
                "--input",
                str(capture),
                "--batch-size",
                "1",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"frames": 2' in output

    imported = RecordingStore(destination_dir)
    try:
        rows = imported.list_recordings()
        assert len(rows) == 1
        restored = imported.load_frames(rows[0]["id"])
        assert [item.model_dump() for item in restored] == [
            item.model_dump() for item in expected
        ]
    finally:
        imported.close()
