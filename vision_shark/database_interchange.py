from __future__ import annotations

import hashlib
import io
import os
import re
import uuid
from pathlib import Path

from .dbc import parse_database

SUPPORTED_DATABASE_FORMATS = frozenset({"dbc", "arxml", "kcd", "sym", "fibex"})
_XML_DATABASE_FORMATS = frozenset({"arxml", "kcd", "fibex"})
_MAX_DATABASE_BYTES = 256 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


class DatabaseInterchangeUnavailable(RuntimeError):
    """Raised when the optional CAN-database dependency is unavailable."""


def _canmatrix():
    try:
        import canmatrix
        import canmatrix.formats as formats
    except ImportError as exc:
        raise DatabaseInterchangeUnavailable(
            "CAN database interchange requires the database extra: "
            "pip install 'vision-shark-app[database]'"
        ) from exc
    return canmatrix, formats


def _normalise_format(value: str) -> str:
    fmt = str(value).strip().lower().lstrip(".")
    if fmt == "xml":
        raise ValueError("XML is ambiguous; specify arxml, kcd or fibex explicitly")
    if fmt not in SUPPORTED_DATABASE_FORMATS:
        allowed = ", ".join(sorted(SUPPORTED_DATABASE_FORMATS))
        raise ValueError(f"unsupported CAN database format; expected one of: {allowed}")
    return fmt


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _preflight_source(path: Path, fmt: str) -> dict:
    if not path.is_file():
        raise ValueError("database input must be an existing regular file")
    size = path.stat().st_size
    if size < 1:
        raise ValueError("database input is empty")
    if size > _MAX_DATABASE_BYTES:
        raise ValueError("database input exceeds 256 MiB review limit")
    if fmt in _XML_DATABASE_FORMATS:
        previous = b""
        with path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                probe = (previous + block).upper()
                if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
                    raise ValueError(
                        "XML database contains a DTD/entity declaration and is rejected"
                    )
                previous = probe[-32:]
    return {"bytes": size, "sha256": _sha256_file(path)}


def _load_cluster(path: Path, fmt: str):
    _, formats = _canmatrix()
    try:
        cluster = formats.loadp(str(path), import_type=fmt)
    except Exception as exc:
        raise ValueError(f"failed to parse {fmt} database: {exc}") from exc
    if not cluster:
        raise ValueError(f"{fmt} database contained no CAN matrices")
    return cluster


def _number(value):
    if value is None:
        return None
    return str(value)


def _matrix_snapshot(name: str, matrix) -> dict:
    frames = []
    signals = 0
    runtime_issues: list[str] = []
    for frame in matrix.frames:
        frame_signals = []
        if getattr(frame, "is_complex_multiplexed", False):
            runtime_issues.append(f"{frame.name}: complex multiplexing")
        if getattr(frame, "pdus", None):
            runtime_issues.append(f"{frame.name}: PDU container")
        if int(frame.size) not in {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64}:
            runtime_issues.append(f"{frame.name}: unsupported payload length {frame.size}")
        for signal in frame.signals:
            signals += 1
            if int(signal.size) < 1 or int(signal.size) > 64:
                runtime_issues.append(f"{frame.name}.{signal.name}: signal width {signal.size}")
            if getattr(signal, "is_float", False):
                runtime_issues.append(f"{frame.name}.{signal.name}: floating-point signal")
            if getattr(signal, "mux_val_grp", None):
                runtime_issues.append(
                    f"{frame.name}.{signal.name}: multiplex range/group semantics"
                )
            frame_signals.append(
                {
                    "name": str(signal.name),
                    "start_bit": int(signal.start_bit),
                    "size": int(signal.size),
                    "little_endian": bool(signal.is_little_endian),
                    "signed": bool(signal.is_signed),
                    "factor": _number(signal.factor),
                    "offset": _number(signal.offset),
                    "minimum": _number(signal.min),
                    "maximum": _number(signal.max),
                    "unit": str(signal.unit or ""),
                    "multiplex": None
                    if signal.multiplex is None
                    else str(signal.multiplex),
                    "is_multiplexer": bool(getattr(signal, "is_multiplexer", False)),
                    "mux_value": getattr(signal, "mux_val", None),
                    "value_count": len(getattr(signal, "values", {}) or {}),
                    "is_float": bool(getattr(signal, "is_float", False)),
                }
            )
        frames.append(
            {
                "name": str(frame.name),
                "arbitration_id": int(frame.arbitration_id.id),
                "extended": bool(frame.arbitration_id.extended),
                "size": int(frame.size),
                "can_fd": bool(frame.is_fd or int(frame.size) > 8),
                "multiplexed": bool(frame.is_multiplexed),
                "signal_count": len(frame_signals),
                "signals": frame_signals,
            }
        )
    frames.sort(key=lambda row: (row["arbitration_id"], row["extended"], row["name"]))
    for row in frames:
        row["signals"].sort(key=lambda signal: (signal["start_bit"], signal["name"]))
    return {
        "name": name,
        "frame_count": len(frames),
        "signal_count": signals,
        "contains_fd": any(row["can_fd"] for row in frames),
        "contains_extended": any(row["extended"] for row in frames),
        "runtime_compatible": not runtime_issues,
        "runtime_issues": sorted(set(runtime_issues)),
        "frames": frames,
    }


def _core_semantics(snapshot: dict) -> list[dict]:
    result = []
    for frame in snapshot["frames"]:
        result.append(
            {
                "name": frame["name"],
                "arbitration_id": frame["arbitration_id"],
                "extended": frame["extended"],
                "size": frame["size"],
                "can_fd": frame["can_fd"],
                "signals": [
                    {
                        key: signal[key]
                        for key in (
                            "name",
                            "start_bit",
                            "size",
                            "little_endian",
                            "signed",
                            "factor",
                            "offset",
                            "minimum",
                            "maximum",
                            "unit",
                            "multiplex",
                            "is_multiplexer",
                            "mux_value",
                            "is_float",
                        )
                    }
                    for signal in frame["signals"]
                ],
            }
        )
    return result


def inspect_database(source: str | Path, source_format: str) -> dict:
    path = Path(source)
    fmt = _normalise_format(source_format)
    evidence = _preflight_source(path, fmt)
    canmatrix, _ = _canmatrix()
    cluster = _load_cluster(path, fmt)
    matrices = [
        _matrix_snapshot(str(name or f"matrix_{index + 1}"), matrix)
        for index, (name, matrix) in enumerate(cluster.items())
    ]
    return {
        "source": str(path),
        "source_format": fmt,
        "source_sha256": evidence["sha256"],
        "source_bytes": evidence["bytes"],
        "canmatrix_version": str(getattr(canmatrix, "__version__", "unknown")),
        "matrix_count": len(matrices),
        "frame_count": sum(item["frame_count"] for item in matrices),
        "signal_count": sum(item["signal_count"] for item in matrices),
        "runtime_compatible": all(item["runtime_compatible"] for item in matrices),
        "matrices": matrices,
        "scope": "research database interchange; no vehicle transmit authority",
    }


def _safe_stem(value: str, fallback: str) -> str:
    cleaned = _SAFE_NAME.sub("_", str(value)).strip("._-")
    cleaned = cleaned[:96]
    return cleaned or fallback


def _dump_dbc(matrix) -> bytes:
    _, formats = _canmatrix()
    target = io.BytesIO()
    try:
        formats.dump(matrix, target, "dbc")
    except Exception as exc:
        raise ValueError(f"failed to render DBC: {exc}") from exc
    payload = target.getvalue()
    if not payload:
        raise ValueError("DBC conversion produced no content")
    return payload


def _reload_dbc(payload: bytes):
    _, formats = _canmatrix()
    try:
        cluster = formats.loads(payload, import_type="dbc")
    except Exception as exc:
        raise ValueError(f"generated DBC could not be reloaded: {exc}") from exc
    if not cluster:
        raise ValueError("generated DBC reloaded as an empty database")
    return next(iter(cluster.values()))


def convert_to_dbc(
    source: str | Path,
    source_format: str,
    output_dir: str | Path,
) -> dict:
    """Convert reviewed CAN database input into one DBC per matrix with evidence."""
    source_path = Path(source)
    fmt = _normalise_format(source_format)
    evidence = _preflight_source(source_path, fmt)
    canmatrix, _ = _canmatrix()
    cluster = _load_cluster(source_path, fmt)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise ValueError("output_dir must be a directory")

    outputs = []
    used_names: set[str] = set()
    for index, (matrix_name, matrix) in enumerate(cluster.items(), 1):
        label = str(matrix_name or f"matrix_{index}")
        source_snapshot = _matrix_snapshot(label, matrix)
        payload = _dump_dbc(matrix)
        reloaded = _reload_dbc(payload)
        reloaded_snapshot = _matrix_snapshot(label, reloaded)
        fidelity_ok = _core_semantics(source_snapshot) == _core_semantics(reloaded_snapshot)
        warnings = []
        if not fidelity_ok:
            warnings.append("core semantics changed during DBC normalization")

        runtime_validated = False
        runtime_error = None
        try:
            parse_database(payload.decode("utf-8"))
            runtime_validated = True
        except (UnicodeDecodeError, ValueError) as exc:
            runtime_error = str(exc)
            warnings.append(f"Vision runtime DBC subset rejected output: {runtime_error}")

        stem = _safe_stem(label, f"matrix_{index}")
        candidate = stem
        suffix = 2
        while candidate.lower() in used_names:
            candidate = f"{stem}_{suffix}"
            suffix += 1
        used_names.add(candidate.lower())
        final_path = destination / f"{candidate}.dbc"
        temporary = destination / f".{candidate}.{uuid.uuid4().hex}.partial"
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, final_path)
        finally:
            temporary.unlink(missing_ok=True)

        outputs.append(
            {
                "matrix": label,
                "path": str(final_path),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "core_semantics_preserved": fidelity_ok,
                "runtime_dbc_validated": runtime_validated,
                "runtime_error": runtime_error,
                "warnings": warnings,
                "source_summary": {
                    key: source_snapshot[key]
                    for key in (
                        "frame_count",
                        "signal_count",
                        "contains_fd",
                        "contains_extended",
                        "runtime_compatible",
                        "runtime_issues",
                    )
                },
            }
        )

    return {
        "source": str(source_path),
        "source_format": fmt,
        "source_sha256": evidence["sha256"],
        "source_bytes": evidence["bytes"],
        "target_format": "dbc",
        "canmatrix_version": str(getattr(canmatrix, "__version__", "unknown")),
        "matrix_count": len(outputs),
        "outputs": outputs,
        "all_core_semantics_preserved": all(
            item["core_semantics_preserved"] for item in outputs
        ),
        "all_runtime_dbc_validated": all(
            item["runtime_dbc_validated"] for item in outputs
        ),
        "scope": "research database interchange; no vehicle transmit authority",
    }
