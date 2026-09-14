from __future__ import annotations

from .tuning_core import MemoryImage


def _ihex_record(address: int, kind: int, payload: bytes) -> str:
    body = bytes((len(payload),)) + int(address).to_bytes(2, "big") + bytes((kind,)) + payload
    checksum = (-sum(body)) & 0xFF
    return ":" + (body + bytes((checksum,))).hex().upper()


def export_ihex(image: MemoryImage, record_bytes: int = 16) -> bytes:
    if record_bytes < 1 or record_bytes > 255:
        raise ValueError("Intel HEX record_bytes must be between 1 and 255")
    lines: list[str] = []
    current_upper: int | None = None
    for segment in image.segments:
        offset = 0
        while offset < len(segment.data):
            absolute = segment.address + offset
            upper = (absolute >> 16) & 0xFFFF
            if upper != current_upper:
                lines.append(_ihex_record(0, 0x04, upper.to_bytes(2, "big")))
                current_upper = upper
            low = absolute & 0xFFFF
            room = 0x10000 - low
            size = min(record_bytes, len(segment.data) - offset, room)
            payload = bytes(segment.data[offset : offset + size])
            lines.append(_ihex_record(low, 0x00, payload))
            offset += size
    lines.append(_ihex_record(0, 0x01, b""))
    return ("\n".join(lines) + "\n").encode("ascii")


def _srec_record(kind: str, address: int, address_bytes: int, payload: bytes) -> str:
    count = address_bytes + len(payload) + 1
    body = bytes((count,)) + int(address).to_bytes(address_bytes, "big") + payload
    checksum = (~sum(body)) & 0xFF
    return "S" + kind + (body + bytes((checksum,))).hex().upper()


def export_srec(image: MemoryImage, record_bytes: int = 16) -> bytes:
    if record_bytes < 1 or record_bytes > 250:
        raise ValueError("S-record record_bytes must be between 1 and 250")
    maximum = max(segment.end - 1 for segment in image.segments)
    if maximum <= 0xFFFF:
        data_kind, termination_kind, address_bytes = "1", "9", 2
    elif maximum <= 0xFFFFFF:
        data_kind, termination_kind, address_bytes = "2", "8", 3
    elif maximum <= 0xFFFFFFFF:
        data_kind, termination_kind, address_bytes = "3", "7", 4
    else:
        raise ValueError("S-record address exceeds 32-bit range")
    lines: list[str] = []
    for segment in image.segments:
        for offset in range(0, len(segment.data), record_bytes):
            payload = bytes(segment.data[offset : offset + record_bytes])
            lines.append(_srec_record(data_kind, segment.address + offset, address_bytes, payload))
    lines.append(_srec_record(termination_kind, 0, address_bytes, b""))
    return ("\n".join(lines) + "\n").encode("ascii")


def export_bin(image: MemoryImage) -> bytes:
    if len(image.segments) != 1:
        raise ValueError("flat BIN export requires one contiguous memory segment")
    return bytes(image.segments[0].data)


def export_image(image: MemoryImage, output_format: str | None = None) -> tuple[str, bytes]:
    name = str(output_format or image.source_format).strip().lower().lstrip(".")
    if name in {"bin", "binary"}:
        return "bin", export_bin(image)
    if name in {"hex", "ihex", "intelhex"}:
        return "ihex", export_ihex(image)
    if name in {"srec", "s19", "s28", "s37", "motorola"}:
        return "srec", export_srec(image)
    raise ValueError("supported output formats: bin, ihex, srec")
