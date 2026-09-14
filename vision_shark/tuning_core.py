from __future__ import annotations

import hashlib
import json
import zlib
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

_MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class MapDefinition(BaseModel):
    map_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["scalar", "axis", "table"]
    address: int = Field(ge=0, le=0xFFFFFFFF)
    rows: int = Field(default=1, ge=1, le=512)
    cols: int = Field(default=1, ge=1, le=512)
    element_width: Literal[1, 2, 4] = 2
    byte_order: Literal["little", "big"] = "big"
    signed: bool = False
    factor: float = 1.0
    offset: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    unit: str = Field(default="", max_length=48)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.kind in {"scalar", "axis"} and self.rows != 1:
            raise ValueError("scalar and axis maps must have rows=1")
        if self.kind == "scalar" and self.cols != 1:
            raise ValueError("scalar maps must have cols=1")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if self.factor == 0:
            raise ValueError("factor cannot be zero")
        return self

    @property
    def count(self) -> int:
        return self.rows * self.cols

    @property
    def byte_length(self) -> int:
        return self.count * self.element_width


class CalibrationDefinition(BaseModel):
    definition_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
    name: str = Field(min_length=1, max_length=160)
    maps: list[MapDefinition] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def unique_maps(self):
        ids = [item.map_id for item in self.maps]
        if len(ids) != len(set(ids)):
            raise ValueError("map_id values must be unique")
        return self

    def by_id(self) -> dict[str, MapDefinition]:
        return {item.map_id: item for item in self.maps}

    def sha256(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()


class MapEdit(BaseModel):
    map_id: str
    values: list[float] = Field(min_length=1, max_length=262_144)


class PatchEntry(BaseModel):
    map_id: str | None = None
    address: int = Field(ge=0, le=0xFFFFFFFF)
    before_hex: str
    after_hex: str

    @model_validator(mode="after")
    def validate_payload(self):
        if len(self.before_hex) % 2 or len(self.after_hex) % 2:
            raise ValueError("patch hex must have an even length")
        try:
            before = bytes.fromhex(self.before_hex)
            after = bytes.fromhex(self.after_hex)
        except ValueError as exc:
            raise ValueError("patch payload must be hexadecimal") from exc
        if len(before) != len(after):
            raise ValueError("patch before/after lengths must match")
        return self


@dataclass
class MemorySegment:
    address: int
    data: bytearray

    @property
    def end(self) -> int:
        return self.address + len(self.data)


class MemoryImage:
    def __init__(self, segments: list[MemorySegment], source_format: str):
        ordered = sorted(segments, key=lambda item: item.address)
        if not ordered:
            raise ValueError("memory image contains no data")
        total = sum(len(item.data) for item in ordered)
        if total > _MAX_ARTIFACT_BYTES:
            raise ValueError("artifact exceeds 32 MiB limit")
        last_end = -1
        for item in ordered:
            if item.address < 0 or item.address > 0xFFFFFFFF:
                raise ValueError("segment address out of range")
            if item.address < last_end:
                raise ValueError("memory segments overlap")
            last_end = item.end
        self.segments = ordered
        self.source_format = source_format

    @classmethod
    def from_bin(cls, payload: bytes, base_address: int = 0):
        if not payload:
            raise ValueError("binary artifact is empty")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise ValueError("artifact exceeds 32 MiB limit")
        return cls([MemorySegment(int(base_address), bytearray(payload))], "bin")

    @classmethod
    def from_ihex(cls, payload: bytes):
        try:
            lines = payload.decode("ascii").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError("Intel HEX must be ASCII") from exc
        upper = 0
        data: dict[int, int] = {}
        eof = False
        for line_no, raw_line in enumerate(lines, 1):
            line = raw_line.strip()
            if not line:
                continue
            if not line.startswith(":"):
                raise ValueError(f"Intel HEX line {line_no} missing ':'")
            try:
                record = bytes.fromhex(line[1:])
            except ValueError as exc:
                raise ValueError(f"Intel HEX line {line_no} is not hexadecimal") from exc
            if len(record) < 5:
                raise ValueError(f"Intel HEX line {line_no} is too short")
            count = record[0]
            if len(record) != count + 5:
                raise ValueError(f"Intel HEX line {line_no} length mismatch")
            if sum(record) & 0xFF:
                raise ValueError(f"Intel HEX line {line_no} checksum mismatch")
            offset = int.from_bytes(record[1:3], "big")
            kind = record[3]
            body = record[4:-1]
            if kind == 0x00:
                start = upper + offset
                for index, value in enumerate(body):
                    address = start + index
                    if address in data:
                        raise ValueError(f"Intel HEX line {line_no} overlaps existing data")
                    data[address] = value
            elif kind == 0x01:
                eof = True
                break
            elif kind == 0x02:
                if len(body) != 2:
                    raise ValueError("invalid extended segment address record")
                upper = int.from_bytes(body, "big") << 4
            elif kind == 0x04:
                if len(body) != 2:
                    raise ValueError("invalid extended linear address record")
                upper = int.from_bytes(body, "big") << 16
            elif kind in {0x03, 0x05}:
                continue
            else:
                raise ValueError(f"unsupported Intel HEX record type 0x{kind:02X}")
        if not data:
            raise ValueError("Intel HEX contains no data")
        if not eof:
            raise ValueError("Intel HEX EOF record is missing")
        return cls(_segments_from_sparse(data), "ihex")

    @classmethod
    def from_srec(cls, payload: bytes):
        try:
            lines = payload.decode("ascii").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError("S-record must be ASCII") from exc
        data: dict[int, int] = {}
        for line_no, raw_line in enumerate(lines, 1):
            line = raw_line.strip()
            if not line:
                continue
            if len(line) < 4 or line[0] != "S" or line[1] not in "0123456789":
                raise ValueError(f"S-record line {line_no} has invalid prefix")
            try:
                record = bytes.fromhex(line[2:])
            except ValueError as exc:
                raise ValueError(f"S-record line {line_no} is not hexadecimal") from exc
            if not record:
                raise ValueError(f"S-record line {line_no} is empty")
            count = record[0]
            if len(record) != count + 1:
                raise ValueError(f"S-record line {line_no} length mismatch")
            if (sum(record) & 0xFF) != 0xFF:
                raise ValueError(f"S-record line {line_no} checksum mismatch")
            kind = line[1]
            address_bytes = {"1": 2, "2": 3, "3": 4}.get(kind)
            if address_bytes is None:
                continue
            if len(record) < 1 + address_bytes + 1:
                raise ValueError(f"S-record line {line_no} is too short")
            address = int.from_bytes(record[1 : 1 + address_bytes], "big")
            body = record[1 + address_bytes : -1]
            for index, value in enumerate(body):
                absolute = address + index
                if absolute in data:
                    raise ValueError(f"S-record line {line_no} overlaps existing data")
                data[absolute] = value
        if not data:
            raise ValueError("S-record contains no data")
        return cls(_segments_from_sparse(data), "srec")

    @classmethod
    def parse(cls, payload: bytes, source_format: str, base_address: int = 0):
        name = str(source_format).strip().lower().lstrip(".")
        if name in {"bin", "binary"}:
            return cls.from_bin(payload, base_address)
        if name in {"hex", "ihex", "intelhex"}:
            return cls.from_ihex(payload)
        if name in {"srec", "s19", "s28", "s37", "motorola"}:
            return cls.from_srec(payload)
        raise ValueError("supported artifact formats: bin, ihex, srec")

    def clone(self):
        return MemoryImage([MemorySegment(item.address, bytearray(item.data)) for item in self.segments], self.source_format)

    def read(self, address: int, length: int) -> bytes:
        address = int(address)
        length = int(length)
        if length < 0:
            raise ValueError("length cannot be negative")
        for item in self.segments:
            if item.address <= address and address + length <= item.end:
                start = address - item.address
                return bytes(item.data[start : start + length])
        raise ValueError(f"range 0x{address:X}..0x{address + length:X} is not present in artifact")

    def write(self, address: int, payload: bytes) -> None:
        for item in self.segments:
            if item.address <= address and address + len(payload) <= item.end:
                start = address - item.address
                item.data[start : start + len(payload)] = payload
                return
        raise ValueError("patch range is not present in artifact")

    def summary(self) -> dict:
        return {
            "format": self.source_format,
            "bytes": sum(len(item.data) for item in self.segments),
            "segments": [
                {"address": item.address, "end": item.end, "bytes": len(item.data)} for item in self.segments
            ],
            "sha256": self.sha256(),
        }

    def sha256(self) -> str:
        digest = hashlib.sha256()
        for item in self.segments:
            digest.update(item.address.to_bytes(8, "big"))
            digest.update(len(item.data).to_bytes(8, "big"))
            digest.update(item.data)
        return digest.hexdigest()


def _segments_from_sparse(data: dict[int, int]) -> list[MemorySegment]:
    segments: list[MemorySegment] = []
    addresses = sorted(data)
    start = addresses[0]
    previous = start
    current = bytearray([data[start]])
    for address in addresses[1:]:
        if address == previous + 1:
            current.append(data[address])
        else:
            segments.append(MemorySegment(start, current))
            start = address
            current = bytearray([data[address]])
        previous = address
    segments.append(MemorySegment(start, current))
    return segments


def decode_map(image: MemoryImage, definition: MapDefinition) -> dict:
    raw = image.read(definition.address, definition.byte_length)
    values: list[float] = []
    for offset in range(0, len(raw), definition.element_width):
        integer = int.from_bytes(
            raw[offset : offset + definition.element_width], definition.byte_order, signed=definition.signed
        )
        values.append(integer * definition.factor + definition.offset)
    rows = [values[index : index + definition.cols] for index in range(0, len(values), definition.cols)]
    return {
        "map_id": definition.map_id,
        "name": definition.name,
        "kind": definition.kind,
        "address": definition.address,
        "rows": definition.rows,
        "cols": definition.cols,
        "unit": definition.unit,
        "values": values,
        "matrix": rows,
    }


def encode_map(definition: MapDefinition, values: list[float]) -> bytes:
    if len(values) != definition.count:
        raise ValueError(f"map {definition.map_id} expects {definition.count} values")
    bits = definition.element_width * 8
    low = -(1 << (bits - 1)) if definition.signed else 0
    high = (1 << (bits - 1)) - 1 if definition.signed else (1 << bits) - 1
    output = bytearray()
    for value in values:
        numeric = float(value)
        if definition.minimum is not None and numeric < definition.minimum:
            raise ValueError(f"map {definition.map_id} value is below declared minimum")
        if definition.maximum is not None and numeric > definition.maximum:
            raise ValueError(f"map {definition.map_id} value exceeds declared maximum")
        raw = round((numeric - definition.offset) / definition.factor)
        if raw < low or raw > high:
            raise ValueError(f"map {definition.map_id} encoded value is out of range")
        output.extend(int(raw).to_bytes(definition.element_width, definition.byte_order, signed=definition.signed))
    return bytes(output)


def build_patch(image: MemoryImage, definition: CalibrationDefinition, edits: list[MapEdit]) -> list[PatchEntry]:
    definitions = definition.by_id()
    seen: set[str] = set()
    patch: list[PatchEntry] = []
    for edit in edits:
        if edit.map_id in seen:
            raise ValueError(f"duplicate edit for map {edit.map_id}")
        seen.add(edit.map_id)
        item = definitions.get(edit.map_id)
        if item is None:
            raise ValueError(f"unknown map_id: {edit.map_id}")
        before = image.read(item.address, item.byte_length)
        after = encode_map(item, edit.values)
        if before != after:
            patch.append(
                PatchEntry(map_id=item.map_id, address=item.address, before_hex=before.hex(), after_hex=after.hex())
            )
    patch.sort(key=lambda item: item.address)
    for left, right in zip(patch, patch[1:], strict=False):
        left_end = left.address + len(bytes.fromhex(left.after_hex))
        if left_end > right.address:
            raise ValueError(f"edited maps overlap: {left.map_id} and {right.map_id}")
    return patch


def apply_patch(image: MemoryImage, patch: list[PatchEntry]) -> MemoryImage:
    output = image.clone()
    ordered = sorted(patch, key=lambda item: item.address)
    previous_end = -1
    for item in ordered:
        before = bytes.fromhex(item.before_hex)
        after = bytes.fromhex(item.after_hex)
        if item.address < previous_end:
            raise ValueError("patch entries overlap")
        current = output.read(item.address, len(before))
        if current != before:
            raise ValueError(f"patch preimage mismatch at 0x{item.address:X}")
        output.write(item.address, after)
        previous_end = item.address + len(after)
    return output


def diff_images(baseline: MemoryImage, candidate: MemoryImage, max_regions: int = 4096) -> list[PatchEntry]:
    if len(baseline.segments) != len(candidate.segments):
        raise ValueError("memory layouts differ")
    changes: list[PatchEntry] = []
    for left, right in zip(baseline.segments, candidate.segments, strict=True):
        if left.address != right.address or len(left.data) != len(right.data):
            raise ValueError("memory layouts differ")
        start: int | None = None
        before = bytearray()
        after = bytearray()
        for index, (a, b) in enumerate(zip(left.data, right.data, strict=True)):
            if a == b:
                if start is not None:
                    changes.append(
                        PatchEntry(address=left.address + start, before_hex=before.hex(), after_hex=after.hex())
                    )
                    start = None
                    before = bytearray()
                    after = bytearray()
                continue
            if start is None:
                start = index
            before.append(a)
            after.append(b)
        if start is not None:
            changes.append(PatchEntry(address=left.address + start, before_hex=before.hex(), after_hex=after.hex()))
        if len(changes) > max_regions:
            raise ValueError("binary diff exceeds region limit")
    return changes


def checksum(image: MemoryImage, algorithm: Literal["crc32", "sha256"] = "crc32") -> dict:
    payload = b"".join(bytes(item.data) for item in image.segments)
    if algorithm == "crc32":
        value = f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}"
    elif algorithm == "sha256":
        value = hashlib.sha256(payload).hexdigest()
    else:
        raise ValueError("unsupported checksum algorithm")
    return {"algorithm": algorithm, "value": value, "bytes": len(payload), "layout_sha256": image.sha256()}


def calibration_report(image: MemoryImage, definition: CalibrationDefinition) -> dict:
    decoded = [decode_map(image, item) for item in definition.maps]
    return {
        "artifact": image.summary(),
        "definition_id": definition.definition_id,
        "definition_sha256": definition.sha256(),
        "map_count": len(decoded),
        "maps": decoded,
        "scope": "offline calibration authoring and analysis",
        "vehicle_programming": False,
        "raw_vehicle_tx": False,
    }
