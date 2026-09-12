# OpenClaw vehicle-agent architecture

Vision Shark treats an AI agent as a high-level coordinator, never as the real-time steering/braking/propulsion controller.

## Agent capabilities

The structured bridge can expose configured readers for vehicle state, evidence, diagnostics, route context, driver-monitoring state, sensor health and readiness. Named high-level adapters can expose non-driving convenience functions such as locks, horn, lights, hazards, climate, defrost, windows, charge-port and seat-comfort functions when a vehicle-specific integration has been validated.

Navigation tools can set destinations, add waypoints, reroute, route home, find a safe-stop destination and request routing to a hospital. These are navigation intents; they do not command lateral or longitudinal motion.

## Emergency workflow

Emergency inputs may include a user help request, crash signal, external medical alarm, driver-unresponsive state or severe driver-monitoring alarm. Vision Shark does not diagnose a heart attack. When an emergency signal is accepted, the deterministic coordinator can:

1. request a minimum-risk manoeuvre from a separately validated vehicle controller;
2. share location when available;
3. request a hospital destination/reroute;
4. request emergency-services contact;
5. notify configured emergency contacts.

The agent cannot call a raw CAN, CAN-FD, J2534 or DoIP transmit primitive and cannot directly steer, brake, accelerate, shift gear or release/apply the parking brake. Emergency driving intent is represented as a handoff to `validated_vehicle_controller`.

## Why the boundary exists

Natural-language reasoning, network services and cloud agents are not deterministic automotive control loops. A production automated-driving controller requires independent sensing, ODD enforcement, trajectory validation, watchdogs, safety hardware, actuator interfaces, fault containment and vehicle/track validation. Vision Shark keeps that future controller behind a typed handoff so the OpenClaw layer can make useful high-level decisions without becoming the actuator itself.

## OpenClaw integration contract

`OpenClawBridge` is intentionally provider-based. An OpenClaw deployment can map its structured tools onto the bridge's `read()` and `execute()` calls. Vehicle-specific adapters remain named high-level operations. The bridge publishes its capabilities and reports `direct_driving: false` and `driving_handoff: validated_vehicle_controller`.
