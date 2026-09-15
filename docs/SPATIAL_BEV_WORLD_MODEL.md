# Ray-Aware Spatial BEV World Model

Vision Shark's spatial BEV path preserves camera image structure and uses measured camera calibration to build ray-conditioned image tokens before bird's-eye-view fusion.

This is a training and shadow-evaluation architecture. It does not add live vehicle control or vehicle transmit functions.

## Why this exists

The earlier geometry-aware model encoded each camera into a single global feature vector. That made calibration available to the network but discarded most image-space position before cross-camera fusion.

The spatial path keeps a grid of image features per camera and associates every image token with an ego-frame camera ray derived from the validated calibration registry.

```text
camera images
    -> shared spatial CNN
    -> Htoken x Wtoken feature grid per camera

measured intrinsics + camera_to_ego
    -> pixel ray reconstruction
    -> ray origin + ego-frame direction + normalized UV
    -> ray embedding

visual token + camera ID + rig embedding + ray embedding
    -> multi-camera source token set

learned BEV queries
    -> multi-head cross-attention over all camera spatial tokens
    -> BEV residual/FFN block
    -> temporal fusion with ego history
    -> spatial occupancy / flow / risk heads
    -> global agent + multimodal ego-trajectory heads
```

## Configuration

`WorldModelConfig` adds:

```text
use_spatial_bev
spatial_token_height
spatial_token_width
attention_heads
```

Spatial BEV requires `use_camera_geometry=True`. The hidden dimension must be divisible by the attention-head count.

A typical small research configuration is:

```text
hidden_dim=128
spatial_token_height=4
spatial_token_width=8
bev_height=32
bev_width=32
attention_heads=4
```

That produces 32 image tokens per camera and 1024 learned BEV query cells.

## Ray construction

The 18D calibration vector contains normalized intrinsics followed by the first three rows of `camera_to_ego`.

For each normalized image-grid center `(u,v)` Vision Shark forms the camera-frame ray:

```text
x = (u - cx_norm) / fx_norm
y = (v - cy_norm) / fy_norm
z = 1
```

The direction is normalized and rotated by the measured camera-to-ego rotation. The ray feature supplied to the network is:

```text
camera origin in ego frame: x,y,z
ray direction in ego frame: dx,dy,dz
normalized image location: u,v
```

No Shark camera pose or focal length is hard-coded.

## Training CLI

The spatial architecture is selected explicitly:

```bash
vision-shark-learn train \
  --manifest dataset.json \
  --frame-root /data/shark \
  --calibration-registry calibration.json \
  --spatial-bev \
  --spatial-token-height 4 \
  --spatial-token-width 8 \
  --attention-heads 4 \
  --bev-height 32 \
  --bev-width 32 \
  --output artifacts/shark-spatial-v1.pt \
  --onnx artifacts/shark-spatial-v1.onnx \
  --device cuda \
  --mixed-precision
```

`--spatial-bev` is rejected unless a calibration registry is supplied. The resulting checkpoint records the complete model configuration and calibration-registry SHA-256.

Evaluation needs no architecture flag because it reconstructs the model configuration from checkpoint provenance.

## Spatial outputs

For spatial mode the final BEV feature for each cell is combined with the temporal GRU context, then decoded per cell into:

```text
occupancy_logits [batch, future, bev_h, bev_w]
occupancy_flow   [batch, future, 2, bev_h, bev_w]
risk_logits      [batch, future, bev_h, bev_w]
```

Agent futures and multimodal ego trajectories remain decoded from the global temporal latent so their external contract remains unchanged.

`camera_attention` remains available as a coarse per-camera diagnostic. In spatial mode it is derived from the BEV cross-attention tensor by averaging over BEV cells and image tokens for each camera.

## Compatibility

The spatial path is opt-in. Existing checkpoints retain their original behavior:

```text
legacy: cameras + ego_history
geometry-global: cameras + ego_history + camera_geometry
spatial-BEV: cameras + ego_history + camera_geometry
```

Output names remain stable, so Planning World v2, evaluation and ONNX consumers do not need a different result schema.

## CI learning gate

The normal production CI intentionally does not install the large learning dependency set. A second `learning-smoke` job now installs the optional learning runtime and exercises the spatial model with PyTorch.

The smoke gate verifies:

- spatial configuration invariants;
- calibrated forward pass;
- output tensor shapes;
- normalized camera-attention diagnostics;
- multi-task loss/backpropagation;
- geometry-aware ONNX export and validation.

This separates lightweight product checks from the actual ML runtime validation instead of allowing the trainable path to remain unexecuted in CI.
