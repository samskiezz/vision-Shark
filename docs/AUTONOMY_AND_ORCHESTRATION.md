# Vision orchestration and autonomy runtime

The default product direction is one-button orchestration. Operators should not need to select CAN IDs, DBCs, ISO-TP addresses or internal autonomy nodes during ordinary use.

## Implemented in this repository

- `VisionOrchestrator` owns automatic connection state, passive identification, passive learning and shadow-autonomy execution.
- `VehicleSession` is the authoritative workflow state exposed to the UI/API.
- `LearningEngine` inventories messages and varying byte candidates without promoting hypotheses to vehicle truth.
- `KnowledgeGraph` binds inferred facts to confidence/source metadata.
- `AutonomyRuntime` is an executable shadow pipeline: vehicle state + normalized detections -> localization state -> ODD/health -> behavior -> trajectory -> abstract control target.
- Shadow targets have no transport handle and always carry `live_actuation_allowed=false`.

## Source architecture restored from earlier Vision research

The design incorporates patterns studied from openpilot/opendbc/panda and Autoware: vehicle abstraction, replay-first validation, typed autonomy state, generator/selector separation, ODD/fallback, and independent vehicle safety boundaries. Public BYD-family work remains hypothesis material unless reproduced on the exact Shark 6 build.

## Still required for a physical Shark 6 product

The repository does not yet contain an exact vehicle-validated Shark 6 AU network/ECU/signal pack, production camera/radar drivers, trained perception models, a high-rate sensor data plane, complete localization, production driver monitoring, HIL evidence, or a validated steering/braking/propulsion interface. It therefore must not be described as a finished FSD product.

## Acceptance path

1. Plug a supported passive interface into a Shark 6.
2. `POST /api/vision/connect` discovers and opens an eligible passive interface.
3. `POST /api/vision/identify` builds passive identity evidence.
4. `POST /api/vision/learn` inventories traffic and creates hypotheses.
5. Vehicle-specific evidence is validated and promoted into a versioned vehicle pack.
6. Sensor/autonomy functions run in replay/shadow before any future closed-course active-control validation.
