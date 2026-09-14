from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .tuning_artifacts import export_image
from .tuning_core import (
    CalibrationDefinition,
    MapEdit,
    MemoryImage,
    apply_patch,
    build_patch,
    calibration_report,
    checksum,
    diff_images,
)


def _address(value: str) -> int:
    try:
        result = int(str(value), 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("address must be decimal or 0x-prefixed") from exc
    if result < 0 or result > 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("address must fit in 32 bits")
    return result


def _json_file(path: str):
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"JSON file does not exist: {source}")
    if source.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("JSON file exceeds 8 MiB")
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {source}") from exc


def _definition(path: str) -> CalibrationDefinition:
    try:
        return CalibrationDefinition.model_validate(_json_file(path))
    except ValidationError as exc:
        raise ValueError(f"invalid calibration definition: {exc}") from exc


def _edits(path: str) -> list[MapEdit]:
    value = _json_file(path)
    if not isinstance(value, list) or not value:
        raise ValueError("edits JSON must be a non-empty array")
    try:
        return [MapEdit.model_validate(item) for item in value]
    except ValidationError as exc:
        raise ValueError(f"invalid calibration edits: {exc}") from exc


def _image(path: str, fmt: str, base_address: int) -> MemoryImage:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"artifact does not exist: {source}")
    if source.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("artifact exceeds 32 MiB")
    return MemoryImage.parse(source.read_bytes(), fmt, base_address)


def _print(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _inspect(args) -> int:
    image = _image(args.input, args.format, args.base_address)
    result = image.summary()
    result.update({"scope": "offline", "vehicle_programming": False, "raw_vehicle_tx": False})
    _print(result)
    return 0


def _decode(args) -> int:
    image = _image(args.input, args.format, args.base_address)
    _print(calibration_report(image, _definition(args.definition)))
    return 0


def _build(args) -> int:
    image = _image(args.input, args.format, args.base_address)
    definition = _definition(args.definition)
    patch = build_patch(image, definition, _edits(args.edits))
    candidate = apply_patch(image, patch)
    output_format, payload = export_image(candidate, args.output_format)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    result = {
        "baseline_sha256": image.sha256(),
        "candidate_sha256": candidate.sha256(),
        "definition_id": definition.definition_id,
        "definition_sha256": definition.sha256(),
        "changed_regions": len(patch),
        "changed_bytes": sum(len(bytes.fromhex(item.after_hex)) for item in patch),
        "patch": [item.model_dump(mode="json") for item in patch],
        "output_format": output_format,
        "output": str(target),
        "output_bytes": len(payload),
        "scope": "offline calibration authoring",
        "vehicle_programming": False,
        "raw_vehicle_tx": False,
    }
    _print(result)
    return 0


def _diff(args) -> int:
    baseline = _image(args.baseline, args.baseline_format, args.baseline_base_address)
    candidate = _image(args.candidate, args.candidate_format, args.candidate_base_address)
    patch = diff_images(baseline, candidate, args.max_regions)
    _print(
        {
            "baseline_sha256": baseline.sha256(),
            "candidate_sha256": candidate.sha256(),
            "regions": len(patch),
            "changed_bytes": sum(len(bytes.fromhex(item.after_hex)) for item in patch),
            "patch": [item.model_dump(mode="json") for item in patch],
            "scope": "offline binary comparison",
            "vehicle_programming": False,
            "raw_vehicle_tx": False,
        }
    )
    return 0


def _checksum(args) -> int:
    image = _image(args.input, args.format, args.base_address)
    result = checksum(image, args.algorithm)
    result.update({"scope": "offline", "vehicle_programming": False, "raw_vehicle_tx": False})
    _print(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vision-shark-tune", description="Vision Motorsports offline calibration workspace")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="inspect BIN/Intel HEX/S-record layout and digest")
    inspect.add_argument("--input", required=True)
    inspect.add_argument("--format", required=True, choices=("bin", "ihex", "srec"))
    inspect.add_argument("--base-address", type=_address, default=0)
    inspect.set_defaults(handler=_inspect)

    decode = sub.add_parser("decode", help="decode reviewed calibration maps")
    decode.add_argument("--input", required=True)
    decode.add_argument("--format", required=True, choices=("bin", "ihex", "srec"))
    decode.add_argument("--base-address", type=_address, default=0)
    decode.add_argument("--definition", required=True)
    decode.set_defaults(handler=_decode)

    build = sub.add_parser("build", help="apply reviewed map edits and render a candidate artifact")
    build.add_argument("--input", required=True)
    build.add_argument("--format", required=True, choices=("bin", "ihex", "srec"))
    build.add_argument("--base-address", type=_address, default=0)
    build.add_argument("--definition", required=True)
    build.add_argument("--edits", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--output-format", choices=("bin", "ihex", "srec"))
    build.set_defaults(handler=_build)

    diff = sub.add_parser("diff", help="calculate exact changed byte regions between two artifacts")
    diff.add_argument("--baseline", required=True)
    diff.add_argument("--candidate", required=True)
    diff.add_argument("--baseline-format", required=True, choices=("bin", "ihex", "srec"))
    diff.add_argument("--candidate-format", required=True, choices=("bin", "ihex", "srec"))
    diff.add_argument("--baseline-base-address", type=_address, default=0)
    diff.add_argument("--candidate-base-address", type=_address, default=0)
    diff.add_argument("--max-regions", type=int, default=4096)
    diff.set_defaults(handler=_diff)

    check = sub.add_parser("checksum", help="calculate a deterministic artifact checksum")
    check.add_argument("--input", required=True)
    check.add_argument("--format", required=True, choices=("bin", "ihex", "srec"))
    check.add_argument("--base-address", type=_address, default=0)
    check.add_argument("--algorithm", choices=("crc32", "sha256"), default="crc32")
    check.set_defaults(handler=_checksum)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError) as exc:
        print(f"Tuning workspace error: {exc}", file=sys.stderr)
        return 2


def cli():
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
