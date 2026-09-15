from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class TeslaOSSProfile:
    name: str
    architecture: str
    hostname: str
    kernel_repo: str
    kernel_revision: str
    kernel_defconfig: str
    dts: tuple[str, ...]
    initramfs_target: str
    rootfs: str
    packages: tuple[str, ...]
    capabilities: tuple[str, ...]
    provenance: tuple[str, ...]
    proprietary_autopilot_userspace_present: bool = False


def parse_buildroot_defconfig(text: str) -> dict:
    """Parse the small subset of Buildroot config semantics Vision needs.

    This intentionally does not execute make expressions or shell fragments. It
    only extracts explicit assignments and enabled boolean symbols so public
    Tesla platform configs can be compared with Vision deployment requirements.
    """
    values: dict[str, str | bool] = {}
    enabled: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value == "y":
            values[key] = True
            enabled.add(key)
        elif value == "n":
            values[key] = False
        elif len(value) >= 2 and value[0] == value[-1] == '"':
            values[key] = value[1:-1]
        else:
            values[key] = value
    return {"values": values, "enabled": sorted(enabled)}


def _package_names(enabled: Iterable[str]) -> list[str]:
    prefix = "BR2_PACKAGE_"
    return sorted(item[len(prefix):].lower() for item in enabled if item.startswith(prefix))


def profile_from_defconfig(text: str, *, name: str = "tesla_ap_hw3_model3") -> TeslaOSSProfile:
    parsed = parse_buildroot_defconfig(text)
    values = parsed["values"]
    enabled = parsed["enabled"]
    packages = _package_names(enabled)

    capabilities: list[str] = []
    package_set = set(packages)
    if {"gstreamer1", "libv4l_utils"} & package_set or "v4l2grab" in package_set:
        capabilities.append("camera_video_ingest")
    if "opencv" in package_set:
        capabilities.append("computer_vision_primitives")
    if "can_utils" in package_set:
        capabilities.append("can_tooling")
    if {"protobuf", "protobuf_c", "protobuf3"} & package_set:
        capabilities.append("structured_ipc_serialization")
    if {"eigen", "openblas_target", "ceres_solver", "suitesparse"} & package_set:
        capabilities.append("numerical_optimization")
    if {"strace", "trace_cmd", "linux_tools_perf"} & package_set:
        capabilities.append("runtime_tracing")
    if {"cryptsetup", "libsodium", "mbedtls", "libopenssl_bin"} & package_set:
        capabilities.append("crypto_storage_primitives")
    if {"dbus", "tesla_nanomsg", "libwebsockets", "websocketpp"} & package_set:
        capabilities.append("local_ipc_transport")
    if {"tcpdump", "ethtool", "iproute2", "linuxptp", "ntp"} & package_set:
        capabilities.append("network_time_observability")

    dts = str(values.get("BR2_LINUX_KERNEL_INTREE_DTS_NAME", "")).split()
    rootfs = "squashfs-xz" if values.get("BR2_TARGET_ROOTFS_SQUASHFS4_XZ") is True else "unknown"
    arch = "aarch64" if values.get("BR2_aarch64") is True else "unknown"

    return TeslaOSSProfile(
        name=name,
        architecture=arch,
        hostname=str(values.get("BR2_TARGET_GENERIC_HOSTNAME", "")),
        kernel_repo=str(values.get("BR2_LINUX_KERNEL_CUSTOM_REPO_URL", "")),
        kernel_revision=str(values.get("BR2_LINUX_KERNEL_CUSTOM_REPO_VERSION", "")),
        kernel_defconfig=str(values.get("BR2_LINUX_KERNEL_DEFCONFIG", "")),
        dts=tuple(dts),
        initramfs_target=str(values.get("BR2_PACKAGE_LINUX_INITRAMFS_TARGET", "")),
        rootfs=rootfs,
        packages=tuple(packages),
        capabilities=tuple(sorted(set(capabilities))),
        provenance=(
            "teslamotors/buildroot:buildroot-2019.02:configs/ap-hw3_model3_defconfig",
            "teslamotors/buildroot:buildroot-2019.02:README.Tesla",
            "teslamotors/linux:tesla-4.14-hw3",
        ),
        proprietary_autopilot_userspace_present=False,
    )


def official_hw3_model3_profile() -> dict:
    """Return facts independently extracted from Tesla's published HW3 config.

    Tesla explicitly states its proprietary Autopilot userspace is not included
    in the public Buildroot repository. Vision therefore uses these facts only
    to inform deployment/runtime architecture, never as a claim that FSD source
    code was recovered.
    """
    profile = TeslaOSSProfile(
        name="tesla_ap_hw3_model3",
        architecture="aarch64",
        hostname="ap3",
        kernel_repo="https://github.com/teslamotors/linux.git",
        kernel_revision="31b65cbdceebb35e38a3b25743c25548d594191e",
        kernel_defconfig="board-rev0",
        dts=("turbo/turbo-trav-board-hw31", "turbo/turbo-trav-board-rev-b0"),
        initramfs_target="ap-hw3i_defconfig",
        rootfs="squashfs-xz",
        packages=(
            "alsa_utils",
            "boost",
            "can_utils",
            "ceres_solver",
            "cryptsetup",
            "curl",
            "dbus",
            "eigen",
            "ethtool",
            "gflags",
            "glog",
            "gstreamer1",
            "i2c_tools",
            "iproute2",
            "libgpiod",
            "libsodium",
            "libv4l_utils",
            "linux_tools_perf",
            "linuxptp",
            "mbedtls",
            "ntp",
            "opencv",
            "openblas",
            "openssh",
            "protobuf",
            "rapidjson",
            "runit",
            "sqlite",
            "strace",
            "suitesparse",
            "tcpdump",
            "tesla_nanomsg",
            "trace_cmd",
            "v4l2grab",
            "websocketpp",
            "yavta",
        ),
        capabilities=(
            "camera_video_ingest",
            "can_tooling",
            "computer_vision_primitives",
            "crypto_storage_primitives",
            "local_ipc_transport",
            "network_time_observability",
            "numerical_optimization",
            "runtime_tracing",
            "structured_ipc_serialization",
        ),
        provenance=(
            "teslamotors/buildroot:buildroot-2019.02:README.Tesla",
            "teslamotors/buildroot:buildroot-2019.02:configs/ap-hw3_model3_defconfig",
            "teslamotors/linux:tesla-4.14-hw3",
        ),
        proprietary_autopilot_userspace_present=False,
    )
    return {
        **asdict(profile),
        "vision_mapping": {
            "camera_ingest": ["gstreamer1", "v4l2", "opencv"],
            "vehicle_bus_observation": ["can-utils"],
            "model_math": ["eigen", "openblas", "ceres", "suitesparse"],
            "ipc_and_schema": ["protobuf", "dbus", "nanomsg"],
            "observability": ["perf", "strace", "trace-cmd", "tcpdump"],
            "storage_and_integrity": ["squashfs", "cryptsetup", "sqlite"],
        },
        "fsd_source_recovered": False,
        "reason": "Tesla's published Buildroot README states proprietary Autopilot userspace is not included.",
    }
