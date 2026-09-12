# Vision Shark production gap register

## Closed in software

- Durable recording storage and restartable vehicle knowledge index.
- Passive SocketCAN policy with kernel receive-overflow accounting and kernel timestamps.
- Bounded request bodies with an absolute upload deadline.
- DBC research decoding, semantic signal broker, shared-memory data-plane primitive, sensor health and clock-quality services.
- Calibration registry and covariance-aware localisation core for replay/shadow workflows.
- Immutable dataset/model provenance registry.
- Driver-monitoring state evaluator, ODD/fallback supervisor and executable shadow-autonomy pipeline.
- Deterministic scenario regression support.
- Signed rollback-protected staging for application/model/pack/gateway artifacts. This is not vehicle ECU programming.
- Read-only agent facade with no mutation/transmit/actuation tools.
- CI: tests, compile, JavaScript syntax, implementation-marker rejection, dependency vulnerability audit and CycloneDX SBOM.
- Runtime repository fetching retired with explicit HTTP 410 migration responses.

## Evidence gates that software cannot truthfully invent

The following remain external validation inputs rather than implementation placeholders:

1. Australian BYD Shark 6 exact bus topology, bitrates, pinout and gateway behaviour.
2. Exact ECU identities, firmware variants and diagnostic addresses for target vehicles.
3. Validated Shark signal definitions and signed vehicle pack backed by independent sealed captures.
4. Production camera/radar/lidar hardware drivers, time synchronisation and measured calibration.
5. Trained perception/prediction models with licensed datasets and independent evaluation.
6. Any physical steering, braking or propulsion interface and independent safety island.
7. Closed-loop HIL, closed-course vehicle testing, ISO 26262/SOTIF/21434 evidence and Australian regulatory approval.
8. Automotive gateway DV/PV, secure/measured boot and TPM-backed device attestation.
9. Full Uptane repository/A-B operating-system update deployment and power-cut recovery testing.

`production-passive-shadow` means the software product can be released for passive acquisition, evidence, decoding, learning, replay and non-actuating shadow evaluation. It does not mean autonomous driving has been validated on a BYD Shark 6.
