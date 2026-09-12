# Vision Shark

Vision Shark is a local-first vehicle intelligence and autonomy R&D platform. The operator workflow is intentionally simple while hardware discovery, passive vehicle observation, evidence, learning and shadow autonomy run behind the API.

## One-button workflow

The integrated API now exposes `POST /api/vision/connect`, `/api/vision/identify`, `/api/vision/learn` and `/api/vision/autonomy/shadow`. The orchestrator owns the workflow state instead of requiring the operator to manually select low-level engineering primitives.

## Vehicle platform

- Passive Linux SocketCAN/CAN-FD observation with listen-only enforcement.
- Explicit simulator path; no silent fallback from a failed physical connection.
- Runtime DBC decoding, recent-frame state and evidence-oriented passive learning.
- Vehicle-session state machine and evidence-backed knowledge graph.
- Signal hypotheses remain hypotheses until exact-vehicle evidence validates them.

## Restored autonomy R&D runtime

The repository contains an executable shadow-only autonomy pipeline with typed ego/object/world/trajectory data, localization input fusion, perception normalization, ODD/health evaluation, classical trajectory generation, controlled-stop fallback, trajectory safety checks and abstract control targets. The autonomy runtime has no vehicle-transmit primitive and reports `live_actuation=false`.

The architecture is designed to grow toward camera/radar/lidar model adapters, calibrated sensor ingestion, prediction, richer world modelling, multiple planners, simulation/replay and dataset/model-registry services without coupling those systems to raw vehicle transport.

## Upstream engineering provenance

openpilot/opendbc/panda, Autoware and BYD community research are engineering references and hypothesis sources. Their code is not dynamically downloaded or executed by the operator application, and BYD-family observations are not treated as verified Shark 6 facts.

## Current status

This is development software. It does not claim that an Australian BYD Shark 6 signal map, ECU topology, diagnostic addressing, vehicle actuation, production sensor stack or public-road autonomous-driving safety case has been physically validated. Raw vehicle transmit, live steering/braking/propulsion control and firmware/security bypass are not exposed.

## Verification

The restored orchestration/autonomy modules have dedicated regression tests in `tests/test_orchestrator_autonomy.py`; CI runs the repository pytest suite on every push and pull request. Physical Shark 6 validation remains a hardware evidence gate.
