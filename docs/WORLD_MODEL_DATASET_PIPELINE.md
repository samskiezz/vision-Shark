# World Model Dataset, Training and Evaluation Pipeline

This tranche connects Vision Shark's trainable multi-camera world model to reproducible local datasets, offline training, evaluation, provenance and ONNX export. It remains an offline/shadow research path. No live steering, braking, propulsion, gear, parking-brake, raw vehicle transmit, ECU flashing or security bypass is added.

## End-to-end flow

```text
recorded synchronized camera frames + ego state + labels
    -> DatasetManifest validation / canonical SHA-256
    -> deterministic target split
    -> temporal sequence windows
    -> local-only image loader
    -> fixed-shape multi-task targets
    -> VisionWorldModel training
    -> validation metrics + hard-case ranking
    -> checkpoint + provenance sidecar
    -> immutable dataset/model registry
    -> optional ONNX export
    -> Planning World v2 shadow evaluation
```

## Dataset loader

`vision_shark/autonomy/learning_dataset.py` turns the immutable training manifest into actual multi-camera history tensors.

Important properties:

- histories are grouped by `recording_id` and sorted by timestamp;
- sequence windows enforce a maximum temporal gap;
- target split membership applies to the final/labelled sample while preceding samples remain available as causal history;
- camera sets must remain stable through each history window;
- only local file paths or `file://` references are accepted;
- frame paths must resolve beneath explicit `--frame-root` directories;
- optional per-frame SHA-256 validation detects modified source frames;
- images are converted to RGB, resized and normalized to `[0,1]` tensors;
- ego history uses a stable ordered state vector;
- trajectories, occupancy, occupancy flow, risk and agent forecasts are converted into fixed-shape training targets;
- agent targets are padded to `max_agents` with an explicit validity mask.

The loader does not fetch remote imagery and cannot use a manifest to read arbitrary files outside configured roots.

## Metrics

`vision_shark/autonomy/world_model_metrics.py` implements offline metrics independently of PyTorch:

- occupancy IoU, precision and recall;
- occupancy-flow endpoint error;
- ego trajectory ADE/FDE;
- multimodal minADE/minFDE and best-mode NLL;
- masked agent ADE/FDE;
- aggregation over evaluated samples.

`world_model_evaluator.py` runs those metrics against actual model batches and ranks hard examples by trajectory, occupancy, agent and flow error. Those ranked samples can be fed back into the existing hard-case/data-engine loop.

## Provenance

`learning_provenance.py` connects the learning pipeline to the existing `ProvenanceRegistry`.

Dataset registration binds:

- canonical manifest SHA-256;
- deterministic split hashes;
- license identifier;
- sample count;
- camera contract;
- label schema version.

Model registration binds:

- checkpoint SHA-256;
- registered dataset identities;
- evaluation metrics;
- optional calibration SHA-256;
- checkpoint metadata sidecar.

If a checkpoint sidecar claims a different hash than the actual checkpoint, registration is rejected.

## CLI

Install the optional learning stack:

```bash
pip install -e '.[learning]'
```

Inspect capabilities:

```bash
vision-shark-learn profile
```

Validate a manifest and deterministic split:

```bash
vision-shark-learn manifest-validate \
  --manifest dataset.json \
  --split-salt shark-v1
```

Inspect sequence construction without opening image files:

```bash
vision-shark-learn dataset-inspect \
  --manifest dataset.json \
  --frame-root /data/shark \
  --history-steps 4 \
  --future-steps 10
```

Train, evaluate the best validation checkpoint, rank hard cases and export ONNX:

```bash
vision-shark-learn train \
  --manifest dataset.json \
  --frame-root /data/shark \
  --output artifacts/world-model-v1.pt \
  --onnx artifacts/world-model-v1.onnx \
  --device cuda \
  --epochs 40 \
  --registry artifacts/provenance.json \
  --model-name shark-world-v1
```

Evaluate a saved checkpoint on the deterministic test split:

```bash
vision-shark-learn evaluate \
  --manifest dataset.json \
  --frame-root /data/shark \
  --checkpoint artifacts/world-model-v1.pt \
  --split test \
  --device cuda
```

Dataset and model artifacts can also be registered independently using `register-dataset` and `register-model`.

## Capability truth

This code supplies the actual dataset loader, batchable tensors, training loop, metrics, hard-case ranking, checkpoint persistence, provenance binding, CLI and ONNX export path. It does not supply a labelled BYD Shark camera dataset or pretrained automotive-grade weights. Model quality is therefore determined by the data, labels, compute and validation supplied to the pipeline; the repository does not pretend untrained weights are an autonomous-driving model.
