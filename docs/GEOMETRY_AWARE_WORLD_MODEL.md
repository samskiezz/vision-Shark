# Geometry-Aware World Model

Vision Shark can condition its trainable multi-camera world model on explicit camera geometry instead of relying only on learned camera-slot identity.

The geometry path is intended for measured camera intrinsics/extrinsics from a specific vehicle calibration rig. It does not invent BYD camera parameters. A calibration registry is validated, hashed and bound into checkpoint provenance before geometry-aware training is enabled.

## Calibration contract

Each calibration rig contains one entry per camera:

```json
{
  "calibrations": {
    "shark-au-rig-001": {
      "vehicle_variant": "AU Shark 6",
      "firmware": "measured-build-id",
      "source": "workshop calibration export",
      "cameras": [
        {
          "camera_id": "front",
          "width": 1920,
          "height": 1080,
          "fx": 1210.2,
          "fy": 1208.7,
          "cx": 958.4,
          "cy": 541.1,
          "camera_to_ego": [
            [1.0, 0.0, 0.0, 1.20],
            [0.0, 1.0, 0.0, 0.00],
            [0.0, 0.0, 1.0, 1.42],
            [0.0, 0.0, 0.0, 1.00]
          ]
        }
      ]
    }
  }
}
```

The transform is `camera_to_ego`. Validation checks finite values, a homogeneous bottom row, approximately unit rotation rows and approximate rotation-row orthogonality.

Each camera is converted to an 18-dimensional feature vector:

```text
fx / width
fy / height
cx / width
cy / height
width / height
height / width
camera_to_ego[0:3, 0:4] flattened
```

This keeps focal/principal-point terms scale-normalized while retaining the measured camera pose.

## Immutable identity

Every rig has its own canonical SHA-256. The complete registry also receives a canonical SHA-256 independent of dictionary ordering.

Validate a registry:

```bash
vision-shark-learn calibration-validate \
  --calibration-registry calibration.json
```

The command returns:

- registry SHA-256;
- per-rig SHA-256;
- camera IDs;
- variant / firmware / source metadata;
- geometry-vector width;
- validation status.

The same validator is available at:

```text
POST /api/vision/autonomy/training/calibration/validate
```

## Dataset integration

`TrainingSample.calibration_id` selects the calibration rig for that sample. The sequence dataset resolves the rig for every history step and emits:

```text
cameras          [time, cameras, channels, height, width]
ego_history      [time, ego_state_dim]
camera_geometry  [time, cameras, 18]
```

Training with `--calibration-registry` automatically enables strict calibration mode. Every selected sample must identify a known rig and every rig must contain every camera used by the dataset.

Inspect the resulting contract without loading images:

```bash
vision-shark-learn dataset-inspect \
  --manifest dataset.json \
  --frame-root /data/shark \
  --calibration-registry calibration.json \
  --require-calibration
```

## Model architecture

The geometry-aware model uses three inputs:

```text
camera image -> shared CNN -----------------------+
                                                    |
camera slot -> learned camera embedding ----------+--> camera token
                                                    |
intrinsics/extrinsics -> geometry MLP ------------+

camera tokens -> learned cross-camera attention
              -> temporal GRU with ego history
              -> occupancy / flow / agent / risk / multimodal trajectory heads
```

`WorldModelConfig.use_camera_geometry=True` activates the geometry MLP. Geometry-aware checkpoints therefore require `camera_geometry`; legacy two-input checkpoints remain supported.

## Training

```bash
vision-shark-learn train \
  --manifest dataset.json \
  --frame-root /data/shark \
  --calibration-registry calibration.json \
  --output artifacts/shark-world-geometry-v1.pt \
  --onnx artifacts/shark-world-geometry-v1.onnx \
  --registry artifacts/provenance.json \
  --model-name shark-world-geometry-v1 \
  --device cuda \
  --mixed-precision
```

The checkpoint sidecar stores:

- model configuration including geometry mode;
- dataset SHA-256;
- calibration-registry SHA-256;
- calibration IDs;
- loader configuration;
- validation metrics;
- ranked hard cases;
- checkpoint SHA-256.

When a provenance registry is supplied, the registered model is also bound to the calibration-registry SHA-256.

## Evaluation

A geometry-aware checkpoint cannot be evaluated without a calibration registry. Vision Shark verifies that the supplied registry SHA-256 matches the checkpoint sidecar before inference:

```bash
vision-shark-learn evaluate \
  --manifest dataset.json \
  --frame-root /data/shark \
  --checkpoint artifacts/shark-world-geometry-v1.pt \
  --calibration-registry calibration.json \
  --split test \
  --device cuda
```

The evaluator routes geometry into the model, reports the geometry-aware state and retains calibration IDs on per-sample/hard-case output.

## ONNX interface

Legacy model:

```text
inputs: cameras, ego_history
```

Geometry-aware model:

```text
inputs: cameras, ego_history, camera_geometry
```

All existing world-model output names remain unchanged. The ONNX metadata sidecar records whether the export is geometry-aware, and validation checks the corresponding input contract.

## Capability boundary

This tranche implements calibration validation, deterministic calibration identity, dataset geometry materialization, train/evaluate routing, geometry-conditioned camera fusion, checkpoint provenance and geometry-aware ONNX export. It does not fabricate vehicle calibration values or claim unmeasured camera placement. Real vehicle model quality still depends on measured calibration, synchronized labelled data, training compute and independent validation.
