# Vision Signal Language (VSL1)

VSL1 is Vision Shark's transport-neutral evidence envelope. It does not claim unlike physical links are interchangeable. It preserves transport, layer, channel, identifier/address, timestamp and physical/link metadata while presenting higher-layer payloads in one form.

## Supported front ends

- Classic CAN via SocketCAN: raw CAN data-link frames.
- CAN-FD via SocketCAN: raw CAN-FD frames including BRS/ESI metadata and separate nominal/data bitrate metadata when known.
- SAE J2534 pass-thru imports/adapters: CAN or ISO 15765 payloads normalized with the J2534 protocol identity retained. CAN-FD extensions are named explicitly because API identifiers can vary by J2534 revision/vendor.
- ISO 13400 DoIP/ENET: vehicle discovery and UDS diagnostic payloads over Ethernet/IP.

## Units

VSL parses Hz/kHz/MHz/GHz as physical frequency and bps/kbps/Mbps/Gbps as bit rate. They are separate dimensions and are never silently converted into each other. ns/us/ms/s are time.

Examples:

- `500 kbps` -> `500000 bitrate_bps`
- `2 Mbps` -> `2000000 bitrate_bps`
- `100 MHz` -> `100000000 frequency_hz`
- `1 GHz` -> `1000 MHz`

## Why one ENET cable is not a universal raw-bus probe

J1962/OBD-II is a connector, not one protocol. A vehicle can expose CAN/CAN-FD on CAN pins and Ethernet/DoIP on different physical contacts or through a gateway. DoIP can route UDS diagnostic messages to downstream ECUs, which lets Vision normalize the diagnostic application payload with ISO-TP/J2534 paths. It does not give an Ethernet adapter electrical access to a CAN pair that is not connected to that adapter.

Therefore Vision's one-button workflow discovers what the attached interface and vehicle actually expose, then converts every supported observation to VSL1. It never fabricates raw CAN frames from a DoIP diagnostic response.

## Safety boundary

VSL is an observation/normalization format. The shipped ENET client remains restricted to vehicle identification and allowlisted read-only UDS services. Security access, programming/download, coding, reset, routine/IO control and vehicle actuation are outside this layer.
