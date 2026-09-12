# Communication Robustness Lab

This module covers the development need behind voltage-glitch and communication-fault testing without applying intentional power faults to a driveable Shark 6.

## Operating boundary

On a physical vehicle, Vision Shark remains receive-only/read-only. It may record passive CAN/CAN-FD traffic, imported or observed diagnostic responses, communication errors, timing gaps and externally measured supply voltage. It does not intentionally sag, spike, interrupt or modulate vehicle supply voltage, and it does not introduce raw CAN transmission or diagnostic write/coding functions.

Intentional voltage-fault profiles are available only as synthetic replay or on an isolated hardware-in-the-loop bench with no physical vehicle attached, no driver present and propulsion disabled. The software model refuses a voltage-fault profile that declares a connected vehicle, mobile vehicle, driver presence or propulsion-enabled state.

## Why this still improves Shark communication work

The lab lets development reproduce parser and acquisition failure conditions deterministically: supply sag, dropout, ripple and spike timelines can be generated as synthetic traces and aligned with replayed captures. This is useful for validating that the reader fails closed, preserves timestamps, identifies gaps/errors and does not silently invent data when a capture becomes degraded.

`communication_health()` reports receive/transmit direction counts, error-frame ratio, observed identifiers, CAN-FD count, per-bus frame rate and timing gaps. These values describe capture quality only; they are not presented as proof of ECU health or physical-layer integrity without separate instrumentation.

## DMO / diagnostic observations

DMO-related research is handled as evidence-gated observation rather than active probing. Captured UDS, DoIP, ISO-TP or vendor diagnostic responses can be imported into `DiagnosticObservation` and classified as a response, timeout, transport error or UDS negative response. The analyzer does not send a request to the vehicle and does not infer proprietary Shark identifiers that have not been physically validated.

This makes it possible to compare observed DMO/module behavior across firmware versions, variants and recordings while preserving the existing evidence rules from the Shark Field Intelligence dossier.

## API surfaces

```text
GET  /api/research/communication/safety-profile
POST /api/research/communication/voltage-replay
GET  /api/research/recordings/{recording_id}/communication-health
POST /api/research/diagnostics/analyze-observation
```

The supported `vision-shark serve` path applies the existing authentication, role, CSRF and idempotency middleware to these endpoints.

## Development sequence

1. Capture the vehicle passively with the normal listen-only path.
2. Record externally measured low-voltage supply data if available.
3. Import any lawful diagnostic responses already captured by approved tooling.
4. Use communication-health analysis to locate timing gaps/error bursts.
5. Reproduce comparable fault timing in synthetic replay or isolated HIL.
6. Validate parser/recovery behavior without energising a driveable vehicle through the fault injector.
7. Promote any Shark-specific DMO interpretation only after independent physical evidence is attached to the appropriate signed VehiclePack.
