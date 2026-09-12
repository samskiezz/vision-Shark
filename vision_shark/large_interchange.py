from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path

from .domain import Frame

_FORMAT_KEY = b"vision.shark.format"
_FORMAT_VALUE = b"frames-v1"
_SOURCE_KEY = b"vision.shark.source"
_REQUIRED_COLUMNS = (
    "ts_ns",
    "bus",
    "arbitration_id",
    "data",
    "extended",
    "can_fd",
    "brs",
    "esi",
    "rtr",
    "error",
    "direction",
)


class LargeInterchangeUnavailable(RuntimeError):
    """Raised when an optional large-capture dependency is unavailable."""


def _pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise LargeInterchangeUnavailable(
            "Parquet support requires the analytics extra: "
            "pip install 'vision-shark-app[analytics]'"
        ) from exc
    return pa, pq


def _schema():
    pa, _ = _pyarrow()
    return pa.schema(
        [
            pa.field("ts_ns", pa.int64(), nullable=False),
            pa.field("bus", pa.string(), nullable=False),
            pa.field("arbitration_id", pa.uint32(), nullable=False),
            pa.field("data", pa.binary(), nullable=False),
            pa.field("extended", pa.bool_(), nullable=False),
            pa.field("can_fd", pa.bool_(), nullable=False),
            pa.field("brs", pa.bool_(), nullable=False),
            pa.field("esi", pa.bool_(), nullable=False),
            pa.field("rtr", pa.bool_(), nullable=False),
            pa.field("error", pa.bool_(), nullable=False),
            pa.field("direction", pa.string(), nullable=False),
        ],
        metadata={_FORMAT_KEY: _FORMAT_VALUE, _SOURCE_KEY: b"vision-shark"},
    )


def _frame_columns(frames: list[Frame]) -> dict[str, list]:
    return {
        "ts_ns": [frame.ts_ns for frame in frames],
        "bus": [frame.bus for frame in frames],
        "arbitration_id": [frame.arbitration_id for frame in frames],
        "data": [bytes.fromhex(frame.data) for frame in frames],
        "extended": [frame.extended for frame in frames],
        "can_fd": [frame.can_fd for frame in frames],
        "brs": [frame.brs for frame in frames],
        "esi": [frame.esi for frame in frames],
        "rtr": [frame.rtr for frame in frames],
        "error": [frame.error for frame in frames],
        "direction": [frame.direction for frame in frames],
    }


def _chunks(frames: Iterable[Frame], size: int) -> Iterator[list[Frame]]:
    chunk: list[Frame] = []
    for frame in frames:
        chunk.append(frame)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parquet(
    frames: Iterable[Frame],
    target: str | Path,
    *,
    row_group_size: int = 65_536,
    compression: str = "zstd",
) -> dict:
    """Write frames without materialising the full capture in memory."""
    if row_group_size < 1 or row_group_size > 1_000_000:
        raise ValueError("row_group_size must be between 1 and 1000000")
    pa, pq = _pyarrow()
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
    schema = _schema()
    rows = 0
    groups = 0
    writer = None
    try:
        writer = pq.ParquetWriter(
            str(temporary),
            schema,
            compression=compression,
            use_dictionary=["bus", "direction"],
            write_statistics=True,
        )
        for chunk in _chunks(frames, row_group_size):
            for frame in chunk:
                if frame.ts_ns > 9_223_372_036_854_775_807:
                    raise ValueError("frame timestamp exceeds Parquet int64 range")
            table = pa.Table.from_pydict(_frame_columns(chunk), schema=schema)
            writer.write_table(table, row_group_size=len(chunk))
            rows += len(chunk)
            groups += 1
        writer.close()
        writer = None
        os.replace(temporary, destination)
    except Exception:
        if writer is not None:
            writer.close()
        temporary.unlink(missing_ok=True)
        raise
    return {
        "format": "parquet",
        "schema": "vision-shark-frames-v1",
        "rows": rows,
        "row_groups": groups,
        "bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
        "path": str(destination),
    }


def iter_parquet(
    source: str | Path,
    *,
    batch_size: int = 65_536,
    max_frames: int = 10_000_000,
) -> Iterator[Frame]:
    """Read a Vision Parquet capture in bounded batches and validate each frame."""
    if batch_size < 1 or batch_size > 1_000_000:
        raise ValueError("batch_size must be between 1 and 1000000")
    if max_frames < 1:
        raise ValueError("max_frames must be positive")
    _, pq = _pyarrow()
    parquet = pq.ParquetFile(str(Path(source)))
    metadata = parquet.schema_arrow.metadata or {}
    if metadata.get(_FORMAT_KEY) != _FORMAT_VALUE:
        raise ValueError("Parquet file is not a Vision Shark frames-v1 capture")
    missing = set(_REQUIRED_COLUMNS) - set(parquet.schema_arrow.names)
    if missing:
        raise ValueError(
            f"Parquet capture is missing columns: {','.join(sorted(missing))}"
        )
    seen = 0
    for batch in parquet.iter_batches(
        batch_size=batch_size,
        columns=list(_REQUIRED_COLUMNS),
    ):
        values = batch.to_pydict()
        for index in range(batch.num_rows):
            seen += 1
            if seen > max_frames:
                raise ValueError("Parquet capture exceeds frame limit")
            payload = values["data"][index]
            if not isinstance(payload, (bytes, bytearray, memoryview)):
                raise ValueError("Parquet frame payload must be binary")
            yield Frame(
                ts_ns=values["ts_ns"][index],
                bus=values["bus"][index],
                arbitration_id=values["arbitration_id"][index],
                data=bytes(payload).hex(),
                extended=values["extended"][index],
                can_fd=values["can_fd"][index],
                brs=values["brs"][index],
                esi=values["esi"][index],
                rtr=values["rtr"][index],
                error=values["error"][index],
                direction=values["direction"][index],
            )


def parquet_info(source: str | Path) -> dict:
    """Return capture metadata without reading frame payloads."""
    _, pq = _pyarrow()
    parquet = pq.ParquetFile(str(Path(source)))
    metadata = parquet.schema_arrow.metadata or {}
    return {
        "format": metadata.get(_FORMAT_KEY, b"").decode("utf-8", errors="replace"),
        "rows": parquet.metadata.num_rows,
        "row_groups": parquet.metadata.num_row_groups,
        "columns": parquet.schema_arrow.names,
    }
