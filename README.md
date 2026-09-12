# Vision Shark

Vision Shark is our local-first vehicle observation, capture, replay, decoding and engineering application. Upstream GitHub projects are engineering inputs, not operator-facing runtime dependencies.

## Current executable scope

- Linux SocketCAN/CAN-FD passive receive path with listen-only checks.
- Simulator explicitly separated from physical interfaces.
- Recording, evidence hashing, replay and runtime DBC decoding.
- DBC research tools, passive recorded ISO-TP reconstruction and capture interchange.
- Explicitly provisioned diagnostic DID/DTC reads.
- Authentication, roles, audit trail, backup/restore and deployment configuration.

## Status

This development build does **not** claim autonomous driving, steering/braking/propulsion control, ECU programming/security unlock, or an exact Australian BYD Shark 6 signal map has been physically validated. Simulator results do not substitute for physical vehicle evidence.

## Verification

The current local source snapshot was rerun before publication: **253 pytest tests passed**. Physical Shark 6 validation is a separate hardware gate.
