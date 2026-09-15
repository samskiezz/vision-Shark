# Open-source autonomy research baseline — 2026-09-15

Vision Shark's autonomy work is derived from public architecture ideas rather than Tesla proprietary FSD code. Tesla has not published its proprietary FSD userspace stack or model weights.

Reviewed public sources:

- commaai/openpilot (MIT): process-separated model, radar, planning, controls, localization, driver monitoring and replay/test architecture. In particular, `plannerd` consumes model/radar/car state, while longitudinal planning arbitrates among cruise, lead/MPC and optional end-to-end acceleration candidates and constrains acceleration/jerk.
- autowarefoundation/vision_pilot (Apache-2.0): hybrid end-to-end architecture with AutoSpeed, AutoSteer and AutoDrive models, longitudinal/lateral fusion, safety guardian, trajectory planning and calibration. The published fusion layer keeps source-specific measurements and uncertainty rather than blindly trusting a single model output.
- autowarefoundation/auto_e2e: end-to-end planning research, useful for candidate trajectory generation and open-loop evaluation concepts.
- Tesla GPL repositories (buildroot, linux, coreboot): useful only for the open-source platform layer. They do not contain Tesla proprietary FSD planner/model/control source.

## Vision Shark implementation direction

The implementation keeps Vision Shark non-actuating while making the shadow stack materially more realistic:

1. Normalize vehicle, lane, object and model-path observations into one ego-frame world model.
2. Maintain source confidence and freshness rather than collapsing every source into one unqualified state.
3. Find the closest in-path object and compute headway/TTC/risk metrics.
4. Generate multiple trajectory candidates: lane-derived, model-derived, confidence-weighted hybrid and controlled-stop.
5. Generate multiple longitudinal candidates: driver/cruise intent, lead-gap constraint and model suggestion; use the most conservative safe target.
6. Score candidates for collision margin, lane/path deviation, acceleration, jerk, curvature, confidence and stale data.
7. Select only candidates that pass a deterministic guardian.
8. Expose full arbitration evidence and shadow-evaluation metrics for replay regression.
9. Keep `live_actuation_allowed=false`, `raw_vehicle_tx=false`; no steering/braking/propulsion transport exists in this stack.

No external source code is copied into Vision Shark. The implementation is original Python using the public architectural concepts above.
