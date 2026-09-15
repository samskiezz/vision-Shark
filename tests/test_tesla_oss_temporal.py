from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.autonomy.temporal_world import TemporalShadowRuntime, TemporalWorldModel
from vision_shark.autonomy.tesla_oss import official_hw3_model3_profile, parse_buildroot_defconfig, profile_from_defconfig


def test_tesla_hw3_profile_contains_real_published_platform_facts():
    profile = official_hw3_model3_profile()
    assert profile["architecture"] == "aarch64"
    assert profile["hostname"] == "ap3"
    assert profile["kernel_repo"].endswith("teslamotors/linux.git")
    assert profile["kernel_revision"] == "31b65cbdceebb35e38a3b25743c25548d594191e"
    assert "turbo/turbo-trav-board-hw31" in profile["dts"]
    assert "camera_video_ingest" in profile["capabilities"]
    assert "can_tooling" in profile["capabilities"]
    assert profile["proprietary_autopilot_userspace_present"] is False
    assert profile["fsd_source_recovered"] is False


def test_buildroot_parser_extracts_packages_and_capabilities():
    text = """
BR2_aarch64=y
BR2_TARGET_GENERIC_HOSTNAME="ap3"
BR2_LINUX_KERNEL_CUSTOM_REPO_URL="https://github.com/teslamotors/linux.git"
BR2_LINUX_KERNEL_CUSTOM_REPO_VERSION="abc123"
BR2_LINUX_KERNEL_DEFCONFIG="board-rev0"
BR2_LINUX_KERNEL_INTREE_DTS_NAME="turbo/a turbo/b"
BR2_PACKAGE_LINUX_INITRAMFS_TARGET="ap-hw3i_defconfig"
BR2_TARGET_ROOTFS_SQUASHFS4_XZ=y
BR2_PACKAGE_GSTREAMER1=y
BR2_PACKAGE_OPENCV=y
BR2_PACKAGE_CAN_UTILS=y
BR2_PACKAGE_PROTOBUF=y
BR2_PACKAGE_EIGEN=y
BR2_PACKAGE_CERES_SOLVER=y
BR2_PACKAGE_STRACE=y
BR2_PACKAGE_CRYPTSETUP=y
BR2_PACKAGE_DBUS=y
BR2_PACKAGE_TCPDUMP=y
"""
    parsed = parse_buildroot_defconfig(text)
    assert parsed["values"]["BR2_TARGET_GENERIC_HOSTNAME"] == "ap3"
    profile = profile_from_defconfig(text)
    assert profile.architecture == "aarch64"
    assert profile.rootfs == "squashfs-xz"
    assert "opencv" in profile.packages
    assert "camera_video_ingest" in profile.capabilities
    assert "can_tooling" in profile.capabilities
    assert "numerical_optimization" in profile.capabilities


def test_temporal_tracker_measures_motion_and_predicts():
    world = TemporalWorldModel()
    first = world.update(10.0, [{"track_id": "lead", "class": "car", "x": 30.0, "y": 0.0, "confidence": 0.9}])
    assert len(first) == 1
    second = world.update(11.0, [{"track_id": "lead", "class": "car", "x": 25.0, "y": 0.0, "confidence": 0.95}])
    track = second[0]
    assert track.vx < 0.0
    prediction = world.predictions()["lead"]
    assert prediction[0]["x"] < track.x
    snapshot = world.snapshot()
    assert snapshot["track_count"] == 1
    assert snapshot["occupancy"]["occupied"]


def test_temporal_shadow_runtime_uses_persistent_track_state():
    runtime = TemporalShadowRuntime()
    common = {
        "ego_speed_ms": 15.0,
        "lane_path": [{"x": 0, "y": 0, "confidence": 0.9}, {"x": 50, "y": 0, "confidence": 0.9}],
        "model_path": [{"x": 0, "y": 0.1, "confidence": 0.8}, {"x": 50, "y": 0.1, "confidence": 0.8}],
        "cruise_target_ms": 20.0,
    }
    runtime.step({**common, "timestamp_s": 1.0, "detections": [{"track_id": "lead", "class": "car", "x": 28.0, "y": 0.0, "confidence": 0.95}]})
    result = runtime.step({**common, "timestamp_s": 2.0, "detections": [{"track_id": "lead", "class": "car", "x": 22.0, "y": 0.0, "confidence": 0.95}]})
    tracks = result["temporal_world"]["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["vx"] < 0.0
    assert result["planner"]["lead"]["present"] is True
    assert result["planner"]["risk"]["risk"] in {"caution", "critical"}
    assert result["shadow_only"] is True
    assert result["live_actuation"] is False
    assert result["raw_vehicle_tx"] is False


def test_tesla_profile_and_temporal_shadow_api(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        profile = client.get("/api/vision/autonomy/tesla-oss-profile")
        assert profile.status_code == 200
        assert profile.json()["hostname"] == "ap3"

        body = {
            "timestamp_s": 1.0,
            "ego_speed_ms": 10.0,
            "detections": [{"track_id": "lead", "class": "car", "x": 25.0, "y": 0.0, "confidence": 0.9}],
            "lane_path": [{"x": 0, "y": 0, "confidence": 0.9}, {"x": 40, "y": 0, "confidence": 0.9}],
            "model_path": [],
            "cruise_target_ms": 15.0,
        }
        response = client.post("/api/vision/autonomy/temporal-shadow", json=body)
        assert response.status_code == 200
        payload = response.json()
        assert payload["architecture"] == "temporal_vision_shadow_v1"
        assert payload["temporal_world"]["track_count"] == 1
        assert payload["live_actuation"] is False

        reset = client.post("/api/vision/autonomy/temporal-shadow/reset")
        assert reset.status_code == 200
        assert reset.json()["reset"] is True
