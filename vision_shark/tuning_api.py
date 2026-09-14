from __future__ import annotations

import base64
import binascii

from fastapi import HTTPException
from pydantic import BaseModel, Field

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

_MAX_API_ARTIFACT_BYTES = 6 * 1024 * 1024


class ArtifactBody(BaseModel):
    format: str = Field(min_length=1, max_length=16)
    data_base64: str = Field(min_length=1, max_length=8 * 1024 * 1024)
    base_address: int = Field(default=0, ge=0, le=0xFFFFFFFF)


class CalibrationDecodeBody(ArtifactBody):
    definition: CalibrationDefinition


class CalibrationPatchBody(CalibrationDecodeBody):
    edits: list[MapEdit] = Field(min_length=1, max_length=4096)
    output_format: str | None = Field(default=None, max_length=16)


class BinaryDiffBody(BaseModel):
    baseline: ArtifactBody
    candidate: ArtifactBody
    max_regions: int = Field(default=4096, ge=1, le=16384)


class ChecksumBody(ArtifactBody):
    algorithm: str = Field(default="crc32", pattern=r"^(crc32|sha256)$")


def _payload(body: ArtifactBody) -> bytes:
    try:
        payload = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "artifact data_base64 is invalid") from exc
    if not payload:
        raise HTTPException(400, "artifact is empty")
    if len(payload) > _MAX_API_ARTIFACT_BYTES:
        raise HTTPException(413, "HTTP artifact exceeds 6 MiB; use local CLI for larger tuning files")
    return payload


def _image(body: ArtifactBody) -> MemoryImage:
    try:
        return MemoryImage.parse(_payload(body), body.format, body.base_address)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def install_tuning_routes(app, audit):
    @app.post("/api/tuning/artifact/inspect")
    def tuning_artifact_inspect(body: ArtifactBody):
        image = _image(body)
        result = image.summary()
        result.update({"scope": "offline", "vehicle_programming": False, "raw_vehicle_tx": False})
        audit.append("tuning", "artifact_inspected", {"format": result["format"], "bytes": result["bytes"], "sha256": result["sha256"]})
        return result

    @app.post("/api/tuning/calibration/decode")
    def tuning_calibration_decode(body: CalibrationDecodeBody):
        try:
            result = calibration_report(_image(body), body.definition)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit.append(
            "tuning",
            "calibration_decoded",
            {
                "definition_id": body.definition.definition_id,
                "definition_sha256": body.definition.sha256(),
                "artifact_sha256": result["artifact"]["sha256"],
                "maps": result["map_count"],
            },
        )
        return result

    @app.post("/api/tuning/calibration/build-patch")
    def tuning_build_patch(body: CalibrationPatchBody):
        image = _image(body)
        try:
            patch = build_patch(image, body.definition, body.edits)
            candidate = apply_patch(image, patch)
            output_format, rendered = export_image(candidate, body.output_format)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if len(rendered) > _MAX_API_ARTIFACT_BYTES:
            raise HTTPException(413, "rendered artifact exceeds 6 MiB HTTP response limit")
        result = {
            "baseline_sha256": image.sha256(),
            "candidate_sha256": candidate.sha256(),
            "definition_id": body.definition.definition_id,
            "definition_sha256": body.definition.sha256(),
            "changed_regions": len(patch),
            "changed_bytes": sum(len(bytes.fromhex(item.after_hex)) for item in patch),
            "patch": [item.model_dump(mode="json") for item in patch],
            "output_format": output_format,
            "candidate_base64": base64.b64encode(rendered).decode("ascii"),
            "scope": "offline calibration authoring",
            "vehicle_programming": False,
            "raw_vehicle_tx": False,
        }
        audit.append(
            "tuning",
            "calibration_patch_built",
            {
                "definition_id": body.definition.definition_id,
                "baseline_sha256": result["baseline_sha256"],
                "candidate_sha256": result["candidate_sha256"],
                "changed_regions": result["changed_regions"],
                "changed_bytes": result["changed_bytes"],
                "output_format": output_format,
            },
        )
        return result

    @app.post("/api/tuning/binary/diff")
    def tuning_binary_diff(body: BinaryDiffBody):
        baseline = _image(body.baseline)
        candidate = _image(body.candidate)
        try:
            patch = diff_images(baseline, candidate, body.max_regions)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        result = {
            "baseline_sha256": baseline.sha256(),
            "candidate_sha256": candidate.sha256(),
            "regions": len(patch),
            "changed_bytes": sum(len(bytes.fromhex(item.after_hex)) for item in patch),
            "patch": [item.model_dump(mode="json") for item in patch],
            "scope": "offline binary comparison",
            "vehicle_programming": False,
            "raw_vehicle_tx": False,
        }
        audit.append("tuning", "binary_diff", {"regions": result["regions"], "changed_bytes": result["changed_bytes"]})
        return result

    @app.post("/api/tuning/checksum")
    def tuning_checksum(body: ChecksumBody):
        image = _image(body)
        try:
            result = checksum(image, body.algorithm)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        result.update({"scope": "offline", "vehicle_programming": False, "raw_vehicle_tx": False})
        audit.append("tuning", "checksum_calculated", {"algorithm": result["algorithm"], "value": result["value"], "bytes": result["bytes"]})
        return result
