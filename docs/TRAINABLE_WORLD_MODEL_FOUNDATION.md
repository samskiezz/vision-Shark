# Vision Shark Trainable World Model Foundation

Vision Shark now contains a native trainable multi-camera temporal world-model foundation intended for offline research, recorded-data learning, simulation and shadow evaluation. It is not a vehicle-control interface and exposes no live steering, braking, propulsion, gear, parking-brake, raw CAN transmit, ECU flashing or security-bypass path.

## Architecture

`vision_shark/autonomy/learned_world.py` implements an optional PyTorch backend with a real differentiable model:

1. A shared convolutional image encoder processes every camera.
2. Learned camera-ID embeddings preserve view identity.
3. Learned camera attention fuses the surround-camera features at every history step.
4. Ego-state history is encoded separately.
5. A temporal GRU fuses visual and ego history.
6. Independent trainable heads emit future occupancy, occupancy flow, agent futures, a risk field, multimodal ego trajectories and trajectory-mode logits.
7. `world_model_loss` jointly trains those products with BCE, Smooth-L1, best-mode trajectory regression and trajectory-mode classification.

The default configuration uses six cameras, a 128-dimensional latent state, a 32x32 BEV grid, ten future steps at 200 ms spacing, six ego trajectory modes and 32 forecast agents. Every dimension is configurable.

## Data contract

`vision_shark/autonomy/training_contracts.py` defines immutable training records for synchronized camera frame references, ego state, calibration references, labels, scenario tags and metadata. Dataset manifests support:

- per-sample validation;
- required-camera enforcement;
- duplicate detection;
- canonical JSON representation;
- deterministic SHA-256 dataset identity;
- deterministic train/validation/test assignment from sample IDs and a split salt.

This lets the existing hard-case mining system emit a reproducible training queue instead of an informal list of interesting clips.

## Training pipeline

`vision_shark/autonomy/training.py` provides a working PyTorch training loop with:

- AdamW optimization;
- deterministic seed support;
- gradient clipping;
- multi-task loss composition;
- training and validation epochs;
- best-validation model restoration;
- checkpoint persistence;
- checkpoint SHA-256;
- model configuration, training configuration, dataset hash and metrics embedded in checkpoint provenance.

Install the optional backend with:

```bash
pip install -e '.[learning]'
```

The `learning` extra contains PyTorch, ONNX and ONNX Runtime so the learned model can be trained and later connected to the repository's existing inference/runtime architecture.

## Planning World bridge

`vision_shark/autonomy/world_model_bridge.py` converts native learned outputs into the same model-interchange structure used by Planning World v2. This means learned trajectories still pass through the existing counterfactual policy evaluation, while learned occupancy, flow, agent forecasts, risk and camera-attention evidence remain available for analysis.

The model family is registered as `vision_world_model` in `model_adapters.py`, alongside METEOR, AutoE2E, openpilot-style policy outputs and Alpamayo-style trajectory outputs.

## Offline API

The following routes are installed:

```text
GET  /api/vision/autonomy/training/profile
POST /api/vision/autonomy/training/model-profile
POST /api/vision/autonomy/training/manifest/validate
POST /api/vision/autonomy/training/bridge
```

These routes validate data/model contracts and convert stored inference results. They do not launch live vehicle control or perform vehicle transmission.

## What is real now

The repository now contains a differentiable multi-camera model, real PyTorch training/loss/checkpoint code, deterministic dataset contracts, a model-output bridge, a registered native model family and API/test coverage. When the learning extra is installed, a forward pass, loss calculation and backward pass are executable.

## What still requires project data and compute

The repository does not ship pretrained Vision Shark weights, a labelled Shark surround-camera dataset, automotive-grade validation, or a trained production model. Those require recorded data, calibration, labels, GPU training and measured evaluation. The architecture and training path are now present so those assets can be added without replacing the surrounding Planning World, data-engine or evidence systems.
