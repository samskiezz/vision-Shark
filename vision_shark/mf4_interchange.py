from __future__ import annotations

import hashlib
from collections.abc import Iterator
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

from .domain import Frame, LEGAL_FD_LENGTHS

_MAX_MDF_BYTES = 64 * 1024 * 1024 * 1024
_REQUIRED_DATA_FIELDS = (
    "CAN_DataFrame.BusChannel",
    "CAN_DataFrame.ID",
    "CAN_DataFrame.IDE",
    "CAN_DataFrame.DataLength",
    "CAN_DataFrame.DataBytes",
    "CAN_DataFrame.EDL",
)
_OPTIONAL_DATA_FIELDS = (
    "CAN_DataFrame.DLC",
    "CAN_DataFrame.Dir",
    "CAN_DataFrame.BRS",
    "CAN_DataFrame.ESI",
)


class Mf4InterchangeUnavailable(RuntimeError):
    """Raised when the optional MDF/MF4 dependency is unavailable."""


def _asammdf():
    try:
        import asammdf
        from asammdf import MDF
        from asammdf.blocks import v4_constants as v4c
    except ImportError as exc:
        raise Mf4InterchangeUnavailable(
            "MDF4 support requires the measurement extra: "
            "pip install 'vision-shark-app[measurement]'"
        ) from exc
    return asammdf, MDF, v4c


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _preflight(path: Path) -> dict:
    if not path.is_file():
        raise ValueError("MDF input must be an existing regular file")
    size = path.stat().st_size
    if size < 1:
        raise ValueError("MDF input is empty")
    if size > _MAX_MDF_BYTES:
        raise ValueError("MDF input exceeds 64 GiB local review limit")
    with path.open("rb") as handle:
        header = handle.read(8)
    if not header.startswith(b"MDF"):
        raise ValueError("input does not have an MDF file identifier")
    return {"bytes": size, "sha256": _sha256(path)}


def _channel_names(group) -> set[str]:
    names: set[str] = set()
    for channel in getattr(group, "channels", ()):
        name = getattr(channel, "name", None)
        if name:
            names.add(str(name))
    return names


def _classify_group(group, v4c) -> dict:
    channel_group = group.channel_group
    names = _channel_names(group)
    source = getattr(channel_group, "acq_source", None)
    flags = int(getattr(channel_group, "flags", 0) or 0)
    is_bus_event = bool(flags & int(v4c.FLAG_CG_BUS_EVENT))
    is_can = bool(source is not None and getattr(source, "bus_type", None) == v4c.BUS_TYPE_CAN)
    event_type = "other"
    root_name = None
    for candidate, label in (
        ("CAN_DataFrame", "data"),
        ("CAN_RemoteFrame", "remote"),
        ("CAN_ErrorFrame", "error"),
    ):
        if candidate in names or any(name.startswith(candidate + ".") for name in names):
            root_name = candidate
            event_type = label
            break
    required_present = all(
        field in names or any(name.endswith(field) for name in names)
        for field in _REQUIRED_DATA_FIELDS
    )
    reasons: list[str] = []
    if not is_bus_event:
        reasons.append("channel group is not marked as an MDF bus event")
    if not is_can:
        reasons.append("channel-group acquisition source is not CAN")
    if event_type != "data":
        reasons.append("only CAN_DataFrame groups are imported as Vision raw frames")
    if event_type == "data" and not required_present:
        missing = [
            field
            for field in _REQUIRED_DATA_FIELDS
            if field not in names and not any(name.endswith(field) for name in names)
        ]
        reasons.append("missing fields: " + ", ".join(missing))
    return {
        "event_type": event_type,
        "root_name": root_name,
        "bus_event": is_bus_event,
        "can_source": is_can,
        "cycles": int(getattr(channel_group, "cycles_nr", 0) or 0),
        "channel_count": len(names),
        "channels": sorted(names),
        "importable_raw_can": is_bus_event and is_can and event_type == "data" and required_present,
        "reasons": reasons,
    }


def inspect_mf4(source: str | Path) -> dict:
    path = Path(source)
    evidence = _preflight(path)
    asammdf, MDF, v4c = _asammdf()
    mdf = MDF(path)
    try:
        groups = []
        for index, group in enumerate(mdf.groups):
            item = _classify_group(group, v4c)
            item["index"] = index
            groups.append(item)
        importable = [item for item in groups if item["importable_raw_can"]]
        remote = [item for item in groups if item["bus_event"] and item["can_source"] and item["event_type"] == "remote"]
        errors = [item for item in groups if item["bus_event"] and item["can_source"] and item["event_type"] == "error"]
        return {
            "source": str(path),
            "source_bytes": evidence["bytes"],
            "source_sha256": evidence["sha256"],
            "asammdf_version": str(getattr(asammdf, "__version__", "unknown")),
            "mdf_version": str(mdf.version),
            "group_count": len(groups),
            "can_bus_event_groups": sum(1 for item in groups if item["bus_event"] and item["can_source"]),
            "importable_data_groups": len(importable),
            "importable_data_cycles": sum(item["cycles"] for item in importable),
            "remote_groups_detected_not_imported": len(remote),
            "error_groups_detected_not_imported": len(errors),
            "groups": groups,
            "scope": "raw CAN reconstruction only from explicit MDF4 CAN bus-event groups; generic measurement channels are not treated as CAN frames",
        }
    finally:
        mdf.close()


def _timestamp_ns(value) -> int:
    scaled = Decimal(str(value)) * Decimal(1_000_000_000)
    rounded = scaled.to_integral_value(rounding=ROUND_HALF_EVEN)
    result = int(rounded)
    if result < 0:
        raise ValueError("MDF CAN frame timestamp is negative")
    return result


def _direction(value) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"rx", "receive", "received"}:
            return "rx"
        if text in {"tx", "transmit", "transmitted"}:
            return "tx"
        return "unknown"
    try:
        return "tx" if int(value) else "rx"
    except (TypeError, ValueError):
        return "unknown"


def _field(signal, name: str, *, required: bool = True):
    try:
        return signal[name]
    except (KeyError, ValueError, TypeError, IndexError):
        if required:
            raise ValueError(f"MDF CAN_DataFrame field is unavailable: {name}") from None
        return None


def _row_bytes(value, length: int) -> bytes:
    try:
        payload = bytes(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("MDF CAN_DataFrame.DataBytes is not byte-array compatible") from exc
    if length < 0 or length > 64:
        raise ValueError(f"MDF CAN data length is outside 0..64 bytes: {length}")
    if len(payload) < length:
        raise ValueError("MDF CAN data payload is shorter than DataLength")
    return payload[:length]


def _chunk_frames(data, group_index: int) -> Iterator[Frame]:
    bus_values = _field(data, "CAN_DataFrame.BusChannel")
    id_values = _field(data, "CAN_DataFrame.ID")
    ide_values = _field(data, "CAN_DataFrame.IDE")
    length_values = _field(data, "CAN_DataFrame.DataLength")
    bytes_values = _field(data, "CAN_DataFrame.DataBytes")
    edl_values = _field(data, "CAN_DataFrame.EDL")
    dir_values = _field(data, "CAN_DataFrame.Dir", required=False)
    brs_values = _field(data, "CAN_DataFrame.BRS", required=False)
    esi_values = _field(data, "CAN_DataFrame.ESI", required=False)
    timestamps = data.timestamps
    count = len(timestamps)
    for index in range(count):
        raw_id = int(id_values[index])
        arbitration_id = raw_id & 0x1FFFFFFF
        extended = bool(int(ide_values[index]))
        if not extended and arbitration_id > 0x7FF:
            raise ValueError(
                f"MDF group {group_index} row {index}: standard identifier exceeds 11 bits"
            )
        can_fd = bool(int(edl_values[index]))
        data_length = int(length_values[index])
        if can_fd:
            if data_length not in LEGAL_FD_LENGTHS:
                raise ValueError(
                    f"MDF group {group_index} row {index}: invalid CAN-FD length {data_length}"
                )
        elif data_length > 8:
            raise ValueError(
                f"MDF group {group_index} row {index}: classic CAN length exceeds 8 bytes"
            )
        payload = _row_bytes(bytes_values[index], data_length)
        brs = bool(int(brs_values[index])) if brs_values is not None and can_fd else False
        esi = bool(int(esi_values[index])) if esi_values is not None and can_fd else False
        direction = _direction(dir_values[index] if dir_values is not None else None)
        bus_channel = int(bus_values[index])
        yield Frame(
            ts_ns=_timestamp_ns(timestamps[index]),
            bus=f"mf4-can-{bus_channel}",
            arbitration_id=arbitration_id,
            data=payload.hex(),
            extended=extended,
            can_fd=can_fd,
            brs=brs,
            esi=esi,
            direction=direction,
        )


def iter_mf4_can_frames(
    source: str | Path,
    *,
    batch_size: int = 4096,
    max_frames: int = 10_000_000,
) -> Iterator[Frame]:
    """Stream raw CAN data frames from explicit MDF4 CAN bus-event groups."""
    if batch_size < 1 or batch_size > 1_000_000:
        raise ValueError("batch_size must be between 1 and 1000000")
    if max_frames < 1:
        raise ValueError("max_frames must be positive")
    path = Path(source)
    _preflight(path)
    _, MDF, v4c = _asammdf()
    mdf = MDF(path)
    emitted = 0
    importable_groups = 0
    try:
        for group_index, group in enumerate(mdf.groups):
            descriptor = _classify_group(group, v4c)
            if not descriptor["importable_raw_can"]:
                continue
            importable_groups += 1
            total = descriptor["cycles"]
            offset = 0
            while offset < total:
                count = min(batch_size, total - offset)
                data = mdf.get(
                    "CAN_DataFrame",
                    group_index,
                    record_offset=offset,
                    record_count=count,
                )
                for frame in _chunk_frames(data, group_index):
                    emitted += 1
                    if emitted > max_frames:
                        raise ValueError("MDF raw CAN import exceeds frame limit")
                    yield frame
                offset += count
        if importable_groups == 0:
            raise ValueError(
                "MDF file has no importable explicit CAN_DataFrame bus-event groups; "
                "generic measurement signals are not reconstructed as CAN frames"
            )
    finally:
        mdf.close()
