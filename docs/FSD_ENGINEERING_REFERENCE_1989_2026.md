# FSD Engineering Reference — 1989 to 2026

This document records the public research and open-source architecture concepts used to evolve Vision Shark. It is an engineering lineage and implementation map, not a claim that Tesla proprietary FSD source or weights were recovered.

## Safety/product boundary

Vision Shark autonomy code remains observation, replay, simulation and shadow-evaluation only. It does not expose steering, braking, propulsion, gear, parking-brake, raw CAN transmit, ECU flashing, security bypass or live vehicle control.

## Historical progression

### 1989 — ALVINN
CMU demonstrated a neural network mapping road imagery/range input to steering direction. The enduring idea is learned policy from sensory input, but with tiny capacity and narrow operating domain compared with modern systems.

### 2004–2016 — DAVE / DAVE-2
NVIDIA's end-to-end driving work demonstrated camera-to-steering imitation learning and recovery augmentation. This established the direct policy baseline that later end-to-end systems expanded with temporal state, richer outputs and large-scale fleet data.

### 2018 — ChauffeurNet
Waymo showed that imitation alone is insufficient and trained with perturbed/bad trajectories plus explicit collision, off-road and progress objectives. Vision mapping: policy evaluation must reason about unsafe counterfactual futures, not only imitate the most likely expert path.

### 2019 — Tesla Autonomy Day
Public Tesla presentations emphasized fleet-triggered data collection, shadow-mode evaluation, automatic labeling, hard-example mining and neural perception deployed on a custom on-vehicle compute platform. Vision mapping: scenario mining, immutable evidence and shadow comparison are first-class architecture components.

### 2020 — Lift-Splat-Shoot
Multi-camera image features are lifted into 3D, splatted into bird's-eye view, then used for downstream reasoning. Vision mapping: every camera needs explicit calibration and a common ego/world coordinate frame.

### 2021 — Tesla vector-space and temporal-memory transition
Tesla publicly described replacing hand-coded cross-camera/image-space stitching with neural vector-space representations across cameras and time. Public AI Day material also described separate time-triggered and distance-triggered feature queues so short-term motion history and spatial road context survive different driving conditions, including long stops. Vision mapping: per-camera detections are only an interim baseline; the stable contract is a common planning representation with both temporal and spatial memory.

### 2022 — BEVFormer
Spatiotemporal transformers use calibrated camera geometry plus historical BEV memory. Vision mapping: temporal memory and camera synchronization/calibration quality must be explicit inputs/evidence.

### 2022 — Tesla occupancy / occupancy flow
Tesla publicly described dense video occupancy, semantics and motion/flow for arbitrary geometry and occlusion. Vision mapping: object lists alone are not sufficient; time-indexed occupancy is required beside vector agents.

### 2023 — UniAD
UniAD connects detection, tracking, mapping, motion forecasting, occupancy and planning with planning-oriented query interfaces. Vision mapping: upstream outputs should be evaluated by how well they support safe trajectory selection, not as isolated accuracy tasks.

### 2023 — VAD
VAD uses vectorized agents and map elements as direct planning constraints to reduce dense raster cost while preserving instance-level structure. Vision mapping: keep both occupancy layers and vector lane/agent representations.

### 2023 — GAIA-1
Wayve demonstrated a generative action-conditioned driving world model. Vision mapping: policy candidates should be evaluated against predicted future worlds through a stable counterfactual rollout interface.

### 2024–2026 — end-to-end policy + learned simulator direction
Tesla FSD, openpilot and other research systems increasingly move behavior generation into learned temporal policies. openpilot 0.11 publicly describes training the driving policy using a learned world model/simulator. Vision mapping: keep deterministic transparent rollouts today, but define interfaces that can later accept learned world-model predictions without changing the safety/evaluation API.

### 2025–2026 — VLM/VLA reasoning
SimLingo, DriveLM-style research and NVIDIA Alpamayo combine visual state, language/reasoning and action/trajectory prediction for long-tail cases. Vision mapping: reasoning should annotate candidate generation and hard-case diagnosis, not bypass deterministic safety checks.

### 2026 — AutoE2E multi-view architecture
Autoware AutoE2E exposes a practical open multi-camera architecture with pluggable concat, cross-camera attention and BEV fusion, temporal visual history, ego-motion history and a multi-second trajectory planner. Vision mapping: use explicit camera batch/synchronization/calibration contracts and keep fusion strategy replaceable.

### 2026 — METEOR-style unified multi-task E2E
Autoware Foundation's public METEOR work presents a compact camera-first network whose outputs include depth, segmentation, 2D/3D objects, BEV lanes, occupancy/flow, agent forecasts, traffic-light state, near-field risk and multimodal ego trajectories. Vision mapping: define a single interchange contract where a model can provide any subset of world products and policy candidates without coupling the rest of the stack to one neural architecture.

### 2026 — reasoning VLA and post-training
NVIDIA Alpamayo research exposes a reasoning/action interface and public training recipes including supervised and reinforcement-learning post-training. Vision mapping: reasoning traces may accompany policy candidates as metadata and training evidence, but deterministic safety/counterfactual evaluation remains independent.

## Public/open sources reviewed

- Tesla open-source Buildroot platform: https://github.com/teslamotors/buildroot
- Tesla Linux: https://github.com/teslamotors/linux
- openpilot: https://github.com/commaai/openpilot
- openpilot 0.11 learned-simulator release: https://blog.comma.ai/011release/
- Autoware AutoE2E: https://github.com/autowarefoundation/auto_e2e
- AutoE2E multi-view fusion design: https://github.com/autowarefoundation/auto_e2e/blob/main/Design/multi_view_fusion_architecture.md
- UniAD: https://github.com/OpenDriveLab/UniAD
- VAD: https://github.com/hustvl/VAD
- BEVFormer: https://github.com/fundamentalvision/BEVFormer
- Lift-Splat-Shoot: https://github.com/nv-tlabs/lift-splat-shoot
- NVIDIA Alpamayo: https://github.com/NVlabs/alpamayo
- METEOR / Autoware Foundation public research discussion and published model artifacts

## What Vision Planning World v2 implements now

1. Camera-frame synchronization evidence with expected-camera coverage, temporal span and latency reporting.
2. Camera calibration validation with explicit intrinsics and 4x4 camera-to-ego extrinsics.
3. Pixel + depth to ego-frame projection as a deterministic calibrated baseline.
4. Geometry-aware late multi-camera object fusion with independent-camera provenance.
5. Persistent temporal tracking and motion estimation across frames.
6. Dual time-triggered and distance-triggered temporal feature memory for short-term motion and spatial context.
7. Vector lane-topology graph with neighbors, predecessors, successors, route relevance and speed limits.
8. Multimodal agent forecasting: constant-velocity, deceleration, turn and crossing hypotheses with probabilities.
9. Time-indexed occupancy layers derived from weighted future hypotheses.
10. A common policy-candidate schema for neural/end-to-end models and deterministic fallback planners.
11. Public-model output adapters for METEOR-like multi-task outputs, AutoE2E accel/curvature or trajectory outputs, openpilot-style learned policy outputs and Alpamayo-style trajectory/reasoning outputs.
12. Counterfactual trajectory evaluation against all agent hypotheses, clearance, collision risk, comfort and lane deviation.
13. Policy benchmarking with ADE/FDE, speed/acceleration error and candidate-disagreement metrics against a reference trajectory.
14. Scenario mining tags for desynchronization, missing cameras, stale/uncertain tracks, high latency, low clearance, collision risk and policy ambiguity.
15. Fleet-style hard-case scoring for interventions, safety fallback, collision risk, low clearance, uncertainty, occlusion, rare objects and route ambiguity.
16. Diversity-aware hard-case selection with deterministic scenario fingerprints and per-fingerprint quotas.
17. Offline training-manifest generation with immutable SHA-256 digest and labeling requirements.
18. Deterministic hybrid fallback remains available when no model policy candidate is usable.
19. All outputs are explicitly shadow-only with no live actuator transport or data upload.

## Integration contracts

### Model adapters
`vision_shark/autonomy/model_adapters.py` normalizes external model outputs into Planning World v2. It does not bundle third-party model weights or copy implementation code. This allows independent model processes to emit:

- Cartesian multimodal trajectories;
- acceleration + curvature sequences;
- 3D objects;
- lane topology;
- occupancy/flow products;
- traffic-light/risk products;
- reasoning annotations.

### Fleet data engine
`vision_shark/autonomy/data_engine.py` operationalizes the public fleet-learning/data-engine idea without uploading vehicle data. It scores local shadow scenarios, deduplicates them for diversity, builds a labeling/training queue and benchmarks policy outputs against recorded/reference trajectories.

### World-model seam
Current candidate evaluation is transparent kinematic counterfactual rollout against multimodal agent forecasts. The interface is intentionally stable so a future learned video/world-model simulator can replace or supplement those predictions without changing the policy benchmark or safety evidence schema.

## What is intentionally not claimed yet

- learned feature-level BEV fusion running inside Vision itself
- a trained multi-camera neural backbone bundled with Vision
- a trained learned occupancy network bundled with Vision
- a learned video world-model simulator bundled with Vision
- learned multimodal ego-policy weights bundled with Vision
- Tesla proprietary FSD source or weights
- automotive-grade autonomous driving validation

Those are separate model-training and validation projects. Vision now has the data contracts, camera geometry, dual temporal/spatial memory, temporal world state, multimodal prediction, model interoperability, candidate evaluation, policy benchmarking and fleet-style hard-case mining infrastructure needed to integrate such models without rebuilding the surrounding system.
