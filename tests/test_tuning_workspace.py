import base64

import pytest
from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.tuning_core import (
    CalibrationDefinition,
    MapDefinition,
    MapEdit,
    MemoryImage,
    apply_patch,
    build_patch,
    checksum,
    decode_map,
    diff_images,
)


def definition():
    return CalibrationDefinition(
        definition_id="demo.engine.v1",
        name="Demo calibration",
        maps=[
            MapDefinition(
                map_id="torque.limit",
                name="Torque limit",
                kind="table",
                address=0,
                rows=2,
                cols=2,
                element_width=2,
                byte_order="big",
                signed=False,
                factor=0.1,
                minimum=0,
                maximum=1000,
                unit="Nm",
            )
        ],
    )


def test_binary_decode_patch_and_preimage_guard():
    image = MemoryImage.from_bin(bytes.fromhex("006400c8012c0190"))
    decoded = decode_map(image, definition().maps[0])
    assert decoded["values"] == [10.0, 20.0, 30.0, 40.0]

    patch = build_patch(image, definition(), [MapEdit(map_id="torque.limit", values=[11, 22, 33, 44])])
    assert len(patch) == 1
    assert patch[0].before_hex == "006400c8012c0190"
    candidate = apply_patch(image, patch)
    assert decode_map(candidate, definition().maps[0])["values"] == [11.0, 22.0, 33.0, 44.0]

    stale = MemoryImage.from_bin(bytes.fromhex("006500c8012c0190"))
    with pytest.raises(ValueError, match="preimage mismatch"):
        apply_patch(stale, patch)


def test_binary_diff_round_trip_and_checksums():
    baseline = MemoryImage.from_bin(b"abcdefgh")
    candidate = MemoryImage.from_bin(b"abXXefYh")
    patch = diff_images(baseline, candidate)
    assert [(item.address, item.before_hex, item.after_hex) for item in patch] == [
        (2, b"cd".hex(), b"XX".hex()),
        (6, b"g".hex(), b"Y".hex()),
    ]
    assert apply_patch(baseline, patch).sha256() == candidate.sha256()
    assert checksum(candidate, "crc32")["bytes"] == 8
    assert len(checksum(candidate, "sha256")["value"]) == 64


def test_intel_hex_parser_validates_checksum_and_eof():
    image = MemoryImage.from_ihex(b":0400000001020304F2\n:00000001FF\n")
    assert image.read(0, 4) == b"\x01\x02\x03\x04"
    with pytest.raises(ValueError, match="checksum mismatch"):
        MemoryImage.from_ihex(b":0400000001020304F3\n:00000001FF\n")
    with pytest.raises(ValueError, match="EOF"):
        MemoryImage.from_ihex(b":0400000001020304F2\n")


def test_srec_parser_validates_checksum():
    image = MemoryImage.from_srec(b"S107100001020304DE\nS9030000FC\n")
    assert image.read(0x1000, 4) == b"\x01\x02\x03\x04"
    with pytest.raises(ValueError, match="checksum mismatch"):
        MemoryImage.from_srec(b"S107100001020304DF\n")


def test_map_bounds_and_overlap_protection():
    image = MemoryImage.from_bin(b"\x00" * 16)
    bad = CalibrationDefinition(
        definition_id="bad",
        name="bad",
        maps=[
            MapDefinition(map_id="a", name="a", kind="table", address=0, rows=1, cols=4, element_width=2),
            MapDefinition(map_id="b", name="b", kind="table", address=4, rows=1, cols=4, element_width=2),
        ],
    )
    with pytest.raises(ValueError, match="overlap"):
        build_patch(
            image,
            bad,
            [MapEdit(map_id="a", values=[1, 2, 3, 4]), MapEdit(map_id="b", values=[5, 6, 7, 8])],
        )


def test_tuning_api_decodes_and_builds_patch(tmp_path):
    app = create_app(tmp_path)
    artifact = base64.b64encode(bytes.fromhex("006400c8012c0190")).decode()
    body = {"format": "bin", "data_base64": artifact, "base_address": 0, "definition": definition().model_dump(mode="json")}
    with TestClient(app) as client:
        inspected = client.post("/api/tuning/artifact/inspect", json={"format": "bin", "data_base64": artifact})
        assert inspected.status_code == 200
        assert inspected.json()["bytes"] == 8
        assert inspected.json()["vehicle_programming"] is False

        decoded = client.post("/api/tuning/calibration/decode", json=body)
        assert decoded.status_code == 200
        assert decoded.json()["maps"][0]["values"] == [10.0, 20.0, 30.0, 40.0]

        patched = client.post(
            "/api/tuning/calibration/build-patch",
            json={**body, "edits": [{"map_id": "torque.limit", "values": [12, 24, 36, 48]}]},
        )
        assert patched.status_code == 200
        result = patched.json()
        assert result["changed_regions"] == 1
        assert result["changed_bytes"] == 8
        assert result["baseline_sha256"] != result["candidate_sha256"]
        assert result["vehicle_programming"] is False


def test_tuning_api_binary_diff(tmp_path):
    app = create_app(tmp_path)
    encode = lambda value: base64.b64encode(value).decode()
    with TestClient(app) as client:
        response = client.post(
            "/api/tuning/binary/diff",
            json={
                "baseline": {"format": "bin", "data_base64": encode(b"abcd")},
                "candidate": {"format": "bin", "data_base64": encode(b"abXd")},
            },
        )
        assert response.status_code == 200
        assert response.json()["regions"] == 1
        assert response.json()["changed_bytes"] == 1
