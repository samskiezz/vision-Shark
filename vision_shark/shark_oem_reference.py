from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

SOURCE = {
    "source_kind": "user_provided_oem_extraction",
    "document": "BYD Shark 6 Pickup Truck Circuit Atlas",
    "vehicle": "BYD Shark 6",
    "powertrain": "DMO PHEV",
    "verification": "source_claimed_oem_not_independently_verified",
    "physical_validation": False,
}


class PinEvidence(BaseModel):
    pin: int | str
    function: str = Field(min_length=1, max_length=240)
    wire_color: str | None = Field(default=None, max_length=32)
    network: str | None = Field(default=None, max_length=96)
    validation_state: str = "source_claimed"


class ConnectorEvidence(BaseModel):
    connector_id: str = Field(min_length=1, max_length=64)
    module: str = Field(min_length=1, max_length=160)
    pin_count: int | None = Field(default=None, ge=1, le=512)
    location: str | None = Field(default=None, max_length=200)
    harness: str | None = Field(default=None, max_length=64)
    pins: list[PinEvidence] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=lambda: dict(SOURCE))


class NetworkMember(BaseModel):
    module: str
    connector_id: str
    can_h_pin: int | str
    can_l_pin: int | str


class NetworkSegment(BaseModel):
    name: str
    purpose: str
    members: list[NetworkMember]
    source: dict[str, Any] = Field(default_factory=lambda: dict(SOURCE))


@dataclass(frozen=True)
class DiagramReference:
    diagram_id: str
    title: str


HARNESS_CODES = {
    "A": "Engine harness I",
    "Ab": "Engine harness II",
    "B": "Front compartment harness",
    "C": "Front beam harness",
    "D": "Front bumper harness",
    "G": "Instrument harness I",
    "Gb": "Instrument harness II",
    "K": "Body harness",
    "P": "Ceiling harness",
    "T": "Front left door harness",
    "U": "Front right door harness",
    "V": "Rear left door harness",
    "W": "Rear right door harness",
    "Y": "Trunk harness",
    "R": "Rear bumper harness",
    "HV": "High-voltage harness",
}

WIRE_COLORS = {
    "B": "Black",
    "P": "Pink",
    "Br": "Brown",
    "R": "Red",
    "G": "Green",
    "Sb": "Sky blue",
    "Gr": "Gray",
    "V": "Violet",
    "L": "Blue",
    "W": "White",
    "Lg": "Light green",
    "Y": "Yellow",
    "O": "Orange",
}

NETWORKS = [
    NetworkSegment(
        name="electronic_injection_subnet",
        purpose="Engine/vehicle-control injection network",
        members=[
            NetworkMember(module="ECM", connector_id="A01(A)", can_h_pin=62, can_l_pin=63),
            NetworkMember(module="VCU", connector_id="K49(A)", can_h_pin=49, can_l_pin=48),
        ],
    ),
    NetworkSegment(
        name="energy_network",
        purpose="Hybrid energy-control network",
        members=[
            NetworkMember(module="VCU", connector_id="K49(A)", can_h_pin=56, can_l_pin=57),
            NetworkMember(module="BMS", connector_id="BK51", can_h_pin=5, can_l_pin=6),
            NetworkMember(module="PTC air heater", connector_id="GB34", can_h_pin=13, can_l_pin=14),
        ],
    ),
    NetworkSegment(
        name="chassis_network",
        purpose="Vehicle-control/chassis/SRS network",
        members=[
            NetworkMember(module="VCU", connector_id="K49(A)", can_h_pin=60, can_l_pin=59),
            NetworkMember(module="Airbag controller", connector_id="KG10", can_h_pin=37, can_l_pin=38),
        ],
    ),
    NetworkSegment(
        name="body_network",
        purpose="Body-domain network",
        members=[
            NetworkMember(module="Left domain controller", connector_id="KG64", can_h_pin=56, can_l_pin=57),
            NetworkMember(module="Right domain controller", connector_id="G86(G)", can_h_pin=4, can_l_pin=5),
            NetworkMember(module="Wireless charger", connector_id="Ga91", can_h_pin=8, can_l_pin=7),
        ],
    ),
    NetworkSegment(
        name="smart_access_network",
        purpose="Smart access / immobilizer / NFC network",
        members=[
            NetworkMember(module="Left domain controller", connector_id="KG64", can_h_pin=52, can_l_pin=53),
            NetworkMember(module="Interior smart access", connector_id="GaT21", can_h_pin=3, can_l_pin=4),
            NetworkMember(module="Right domain controller", connector_id="G86(E)", can_h_pin=3, can_l_pin=4),
        ],
    ),
    NetworkSegment(
        name="adas_network",
        purpose="Camera/radar ADAS network",
        members=[
            NetworkMember(module="Multi-purpose camera", connector_id="P13", can_h_pin=4, can_l_pin=8),
            NetworkMember(module="mmWave radar", connector_id="R06", can_h_pin=2, can_l_pin=3),
            NetworkMember(module="ADAS terminator", connector_id="PG87", can_h_pin=2, can_l_pin=1),
        ],
    ),
    NetworkSegment(
        name="radar_private_subnet",
        purpose="Camera-to-radar private subnet",
        members=[
            NetworkMember(module="Multi-purpose camera", connector_id="P13", can_h_pin=3, can_l_pin=7),
            NetworkMember(module="mmWave radar", connector_id="R06", can_h_pin=5, can_l_pin=6),
        ],
    ),
    NetworkSegment(
        name="dc_charging_can",
        purpose="Battery/DC charging communication",
        members=[NetworkMember(module="BMS", connector_id="BK51", can_h_pin=17, can_l_pin=18)],
    ),
    NetworkSegment(
        name="diagnostic_network",
        purpose="DLC diagnostic CAN routed through vehicle gateway",
        members=[NetworkMember(module="DLC", connector_id="G03", can_h_pin=6, can_l_pin=14)],
    ),
]


def _pins(rows: dict[int | str, str]) -> list[PinEvidence]:
    return [PinEvidence(pin=pin, function=function) for pin, function in rows.items()]


CONNECTORS = {
    "G03": ConnectorEvidence(
        connector_id="G03",
        module="OBD2 / DLC",
        pin_count=16,
        location="Driver-side lower dashboard",
        pins=_pins(
            {
                1: "Electronic control subnet CAN_H (DLC2)",
                2: "Electronic control subnet CAN_L (DLC2)",
                4: "Ground",
                5: "Ground",
                6: "Diagnostic network CAN_H",
                9: "Charging subnet CAN_H",
                10: "Charging subnet CAN_L",
                14: "Diagnostic network CAN_L",
                16: "Constant +12 V supply",
            }
        ),
        notes=["ISO 15031-3 / SAE J1962 form factor per supplied reference."],
    ),
    "A01(A)": ConnectorEvidence(
        connector_id="A01(A)",
        module="ECM",
        pin_count=104,
        harness="A",
        pins=_pins(
            {
                1: "Carbon canister control valve",
                11: "Sensor power supply 2",
                12: "Power supply",
                16: "Power supply",
                22: "Heating -",
                23: "Main relay control",
                25: "Ground",
                26: "Ground",
                29: "Crankshaft position sensor ground",
                31: "Crankshaft position sensor power supply",
                32: "5 V power supply",
                34: "Intake manifold pressure sensor power supply",
                35: "EGR position signal power supply",
                39: "Ground",
                41: "Ground",
                42: "Brake switch 1",
                43: "Rear heated oxygen sensor heating",
                44: "Ground",
                45: "Ground",
                46: "Ground",
                50: "Signal ground",
                52: "Intake header temperature and pressure sensor power supply",
                56: "Electronic throttle power supply",
                57: "Power supply",
                58: "Ground",
                59: "Ground",
                62: "Electronic injection network CAN_H",
                63: "Electronic injection network CAN_L",
                64: "Fuel injector 1 ground-wire control",
                65: "Fuel injector 1 power-supply control",
                66: "Fuel injector 2 power-supply control",
                67: "Turbocharger air circulation valve",
                69: "Camshaft position sensor ground",
                74: "Heating component -",
                75: "Ground",
                79: "Ignition coil control 4",
                80: "Ignition coil control 2",
                82: "Constant power supply",
                84: "Crankshaft position sensor",
                85: "Cylinder 4 fuel injector ground control",
                86: "Cylinder 4 fuel injector power-supply control",
                87: "Cylinder 3 fuel injector power-supply control",
                88: "Cylinder 3 fuel injector ground control",
                89: "Cylinder 2 fuel injector ground control",
                94: "Solenoid valve -",
                96: "Air pump -",
                98: "Control signal",
                102: "Ignition coil control 3",
                103: "Ignition coil control 1",
                104: "IG1",
            }
        ),
    ),
    "A01(B)": ConnectorEvidence(
        connector_id="A01(B)",
        module="ECM",
        pin_count=91,
        harness="A",
        pins=_pins(
            {
                1: "Ground",
                2: "Ground",
                3: "Ground",
                4: "Non-continuous power supply 1",
                5: "Non-continuous power supply 4",
                6: "Non-continuous power supply 3",
                9: "Rotating angle signal",
                12: "Intake header pressure sensor signal",
                13: "Rear heated oxygen sensor signal",
                15: "High-pressure fuel pressure sensor",
                17: "Engine coolant temperature sensor",
                18: "Radiator outlet coolant temperature sensor",
                27: "Carbon canister desorption pressure sensor",
                30: "Intake header temperature sensor signal",
                31: "Intake manifold pressure sensor signal",
                33: "Output",
                34: "Electronic throttle feedback signal 2",
                35: "Sensor OUT",
                37: "Fault signal",
                39: "M+",
                40: "Power supply",
                44: "Ground",
                46: "Rear heated oxygen sensor ground",
                47: "Intake manifold pressure sensor ground",
                48: "Sensor ground",
                50: "Intake header pressure sensor ground",
                51: "High-pressure fuel pressure sensor ground",
                52: "Engine coolant temperature sensor ground",
                53: "Radiator outlet coolant temperature sensor ground",
                55: "Ground",
                56: "M+",
                59: "Knock sensor B",
                64: "Sensor OUT",
                66: "Front heated oxygen sensor",
                70: "Camshaft position sensor signal",
                72: "Speed signal",
                73: "M-",
                74: "ETC -",
                75: "Brake switch 2",
                76: "Knock sensor A",
                80: "Pump current",
                81: "Intake manifold temperature sensor signal",
                82: "Electronic throttle signal 1",
                83: "Nernst voltage",
                86: "EGR control signal",
                91: "ETC +",
            }
        ),
    ),
    "K49(A)": ConnectorEvidence(
        connector_id="K49(A)",
        module="VCU",
        pin_count=65,
        harness="K",
        pins=_pins(
            {
                2: "Ground",
                7: "Oil temperature sensor signal",
                8: "Clutch pressure sensor signal",
                12: "Main pressure sensor power supply",
                18: "Clutch pressure sensor ground",
                22: "Main pressure sensor signal",
                24: "IG3 power supply",
                26: "IG3 power supply",
                29: "Ground",
                38: "Clutch pressure sensor power supply",
                39: "IG3 power supply",
                48: "Electronic injection subnet CAN_L",
                49: "Electronic injection subnet CAN_H",
                51: "Brake switch signal active high",
                52: "Ground",
                53: "Ground",
                54: "Ground",
                56: "Energy network CAN_H",
                57: "Energy network CAN_L",
                59: "Chassis network CAN_L",
                60: "Chassis network CAN_H",
                64: "Constant power supply",
                65: "Constant power supply",
            }
        ),
    ),
    "K49(B)": ConnectorEvidence(
        connector_id="K49(B)",
        module="VCU",
        pin_count=65,
        harness="K",
        pins=_pins(
            {
                2: "Undercooling protection solenoid valve signal",
                13: "Electronic control network CAN_H",
                15: "Electronic oil pump control signal",
                16: "Coolant pump PWM signal",
                26: "Electronic control network CAN_L",
                27: "Clutch pressure signal",
                28: "Clutch pressure power supply",
                29: "Electronic fan PWM control",
                31: "Accelerator pedal stroke power supply 2",
                32: "Accelerator pedal stroke power supply 1",
                36: "Ground",
                40: "Main pressure power supply",
                41: "Main pressure signal",
                45: "Accelerator pedal signal 2",
                46: "Accelerator pedal stroke signal 1",
                47: "PWM control",
                48: "Engine electronic coolant pump LIN communication",
                50: "Electronic oil pump relay signal acquisition",
                54: "Power supply of undercooling protection solenoid valve",
                56: "Engine electronic coolant pump PWM communication",
                57: "Electronic fan control signal",
                59: "Accelerator pedal ground",
                60: "Accelerator pedal ground 2",
            }
        ),
    ),
    "BK51": ConnectorEvidence(
        connector_id="BK51",
        module="Battery pack / BMS",
        pin_count=33,
        harness="HV",
        pins=_pins(
            {
                4: "Constant power supply",
                5: "Energy network CAN_H",
                6: "Energy network CAN_L",
                8: "IG3 power supply",
                9: "Ground",
                10: "Ground",
                11: "Charging connection signal",
                12: "A+",
                13: "Collision signal",
                14: "CC2",
                17: "DC charging CAN_H",
                18: "DC charging CAN_L",
                19: "Temperature detection point 1 +",
                20: "Temperature detection point 2 +",
                27: "Temperature detection ground",
                30: "High-voltage interlocking 1 input signal",
                31: "High-voltage interlocking 1 output signal",
                32: "A-",
            }
        ),
        notes=["High-voltage system connector reference; no HV probing procedure is exposed by Vision Shark."],
    ),
    "Ka76(A)": ConnectorEvidence(
        connector_id="Ka76(A)",
        module="Rear drive powertrain",
        pin_count=14,
        pins=_pins(
            {
                1: "Ground",
                2: "Ground",
                3: "Collision signal ground",
                4: "Electronic control network CAN_H",
                5: "Electronic control network CAN_L",
                7: "Collision signal",
                11: "Constant power supply",
                12: "Constant power supply",
            }
        ),
    ),
    "A36": ConnectorEvidence(
        connector_id="A36",
        module="Dual MCU",
        pin_count=32,
        harness="A",
        pins=_pins(
            {
                1: "IG4 power supply 3",
                2: "IG4 power supply 1",
                3: "Ground",
                4: "IG4 power supply 2",
                5: "Ground 1",
                6: "Ground 2",
                7: "Generator COS+",
                8: "Generator COS-",
                10: "Collision signal ground",
                11: "Collision signal",
                13: "Electronic control network CAN_H",
                14: "Electronic control network CAN_L",
                17: "Drive motor winding temperature ground",
                18: "Drive motor winding temperature +",
                19: "Generator winding temperature +",
                20: "Generator winding temperature ground",
                21: "Generator excitation -",
                22: "Generator excitation +",
                23: "Generator resolver shielding ground",
                24: "Drive motor resolver shielding ground",
                25: "Drive motor COS-",
                26: "Drive motor COS+",
                27: "Generator SIN+",
                28: "Generator SIN-",
                29: "Drive motor excitation +",
                30: "Drive motor excitation -",
                31: "Drive motor SIN+",
                32: "Drive motor SIN-",
            }
        ),
    ),
    "KG10": ConnectorEvidence(
        connector_id="KG10",
        module="Airbag controller",
        pin_count=72,
        harness="K",
        pins=_pins(
            {
                7: "Rear right seat belt pretensioner +",
                8: "Rear right seat belt pretensioner -",
                11: "Rear left seat belt pretensioner +",
                12: "Rear left seat belt pretensioner -",
                17: "Driver seat belt pretensioner -",
                18: "Driver seat belt pretensioner +",
                19: "Collision signal",
                21: "Passenger B-pillar acceleration sensor -",
                22: "Passenger B-pillar acceleration sensor +",
                29: "PAB+",
                30: "PAB-",
                31: "Left CAB -",
                32: "Left CAB +",
                33: "DAB+",
                34: "DAB-",
                37: "Chassis network CAN_H",
                38: "Chassis network CAN_L",
                39: "Driver B-pillar acceleration sensor -",
                40: "Driver B-pillar acceleration sensor +",
                45: "Left SAB -",
                46: "Left SAB +",
                47: "Right SAB +",
                48: "Right SAB -",
                49: "Right CAB -",
                50: "Right CAB +",
                51: "Passenger seat belt pretensioner +",
                52: "Passenger seat belt pretensioner -",
                54: "IG1 power supply",
                58: "Ground",
                59: "Passenger door pressure sensor +",
                60: "Passenger door pressure sensor -",
                63: "Driver door pressure sensor +",
                64: "Driver door pressure sensor -",
                65: "Front left collision sensor -",
                66: "Front left collision sensor +",
                67: "Front right collision sensor +",
                68: "Front right collision sensor -",
            }
        ),
        notes=["SRS connector reference only; do not probe inflator/pretensioner firing circuits."],
    ),
    "P13": ConnectorEvidence(
        connector_id="P13",
        module="Multi-purpose camera",
        pin_count=8,
        harness="P",
        pins=_pins(
            {
                3: "Radar private subnet CAN_H",
                4: "ADAS network CAN_H",
                7: "Radar private subnet CAN_L",
                8: "ADAS network CAN_L",
            }
        ),
    ),
    "PG87": ConnectorEvidence(
        connector_id="PG87",
        module="ADAS network termination resistor",
        pin_count=2,
        harness="P",
        pins=_pins({1: "ADAS network CAN_L", 2: "ADAS network CAN_H"}),
    ),
}

ENGINE_COMPONENTS = {
    "A02": {"component": "Desorption pressure sensor", "pins": 3, "functions": "Power, ground, signal"},
    "A03": {"component": "Carbon canister solenoid valve", "pins": 2, "functions": "Power, signal"},
    "A04": {"component": "Intake manifold temp and pressure sensor", "pins": 4, "functions": "Ground, temperature signal, pressure power, pressure signal"},
    "A05": {"component": "Electronic throttle", "pins": 6, "functions": "Power, signal 2, ground, signal 1, control +, control -"},
    "A06": {"component": "Intake header pressure sensor", "pins": 4, "functions": "Ground, temperature signal, power, pressure signal"},
    "A07": {"component": "High-pressure fuel pressure sensor", "pins": 3, "functions": "Ground, signal, power"},
    "A08": {"component": "Engine oil pressure sensor", "pins": 3, "functions": "Power, ground, signal"},
    "A13": {"component": "Knock sensor", "pins": 2, "functions": "Knock A, knock B"},
    "A14": {"component": "EGR valve", "pins": 6, "functions": "M-, M+, power, signal, signal ground"},
    "A17": {"component": "Engine coolant temperature sensor", "pins": 2, "functions": "Ground, signal"},
    "A23": {"component": "VGT turbocharger actuator", "pins": 6, "functions": "M-, M+, signal power, signal out, signal ground"},
    "A24": {"component": "Rear heated oxygen sensor", "pins": 4, "functions": "Ground, signal, heating, heater power"},
    "A26": {"component": "Camshaft position sensor", "pins": 3, "functions": "Power, signal, ground"},
    "A28": {"component": "Front heated oxygen sensor", "pins": 6, "functions": "Ground, heating+, voltage, pump current, heating-, regulating resistor"},
    "A31": {"component": "Crankshaft position sensor", "pins": 3, "functions": "Ground, sensor, power"},
    "A32": {"component": "Low-temperature coolant pump", "pins": 3, "functions": "Power, control, ground"},
    "A33": {"component": "Engine electronic coolant pump", "pins": 4, "functions": "LIN, PWM, negative, positive"},
    "A34": {"component": "Electric compressor", "pins": 8, "functions": "12 V power, CAN_L, CAN_H, ground"},
    "A39": {"component": "Main oil circuit pressure sensor", "pins": 3, "functions": "Power, ground, signal"},
    "A40": {"component": "Electronic oil pump", "pins": 3, "functions": "Power, LIN, ground"},
    "A42": {"component": "Oil temperature sensor", "pins": 2, "functions": "Ground, signal"},
    "A43": {"component": "Clutch pressure sensor", "pins": 3, "functions": "Power, ground, signal"},
    "A45": {"component": "GPF differential pressure sensor", "pins": 3, "functions": "5 V power, ground, signal out"},
    "A46": {"component": "GPF temperature sensor", "pins": 2, "functions": "Control signal, ground"},
    "A47": {"component": "Pressure sensor", "pins": 3, "functions": "Power, ground, signal"},
}

GROUND_POINTS = {
    "engine": ["Ea01", "Ea02", "Ea03", "Ea04", "Ea05", "Ea06", "Ea08", "Ea09"],
    "front_instrument": ["Eb01", "Eb02", "Eb03", "Eb04", "Eb05", "Eb06", "Eb07", "Eb08", "Eb10"],
    "front_compartment": ["Eg01", "Eg04", "Eg05", "Eg06"],
    "floor": ["Ek01", "Ek02", "Ek03", "Ek04", "Ek05"],
    "rear_floor": ["Eka02", "Eka03", "Eka04", "Eka05"],
    "body": ["Ep01"],
}

JUNCTIONS = [
    "AJB01/BJA01", "AJB02/BJA02", "AJB03/BJA03", "DJB01/BJD01", "DJB02/BJD02",
    "GJB01/BJG01", "GJGa01/GaJG01", "GJK01/KJG01", "GJK02/KJG02", "GJK03/KJG03", "GJK04/KJG04",
    "GJT01/TJG01", "UJG01/GJU01", "PJG01/GJP01", "KaJC01/CJKa01", "KaJK01/KJKa01", "KaJK02/KJKa02",
    "KaJK03/KJKa03", "KaJK04/KJKa04", "KaJK05/KJKa05", "KaJY01/YJKa01", "KaJY02/YJKa02", "RJKa01/KaJR01",
    "KJB01/BJK01", "KJB03/BJK03", "KJT01/TJK01", "KJU01/UJK01", "VJK01/KJV01", "WJK01/KJW01",
]

FUSE_BOXES = {
    "front_compartment": ["B44_5", "AB44_3"],
    "instrument_panel": ["G82"],
    "positive": ["KB46_A", "KB46_B", "KB46_C", "KB46_D", "KB46_E"],
    "floor_adapter": ["KB47_1"],
}

G82_OUTPUTS = {
    2: "External power amplifier",
    4: "Trailer hitch power",
    5: "OBD DLC power",
    6: "HUD / instrument cluster",
    7: "High-frequency receiver + smart access",
    8: "Gearshift panel",
    9: "PAD unit",
    10: "Stop light switch",
    11: "Rear left/right radar",
    12: "Multi-function switch, clock spring, ETC, wireless charging, PAD motor",
    16: "Rear drive motor control unit",
    19: "VCU power supply",
    20: "Rear domain control unit",
    21: "Rear domain control unit",
    22: "Driver power seat",
    23: "Front passenger power seat",
    40: "Front compartment fuse box",
    41: "VCU (UMC)",
}

DIAGRAMS = [
    DiagramReference("DT778370", "Vehicle Control (UMC)"),
    DiagramReference("DT778374", "Charging System (European)"),
    DiagramReference("DT778375", "Infotainment"),
    DiagramReference("DT778376", "Horn"),
    DiagramReference("DT778378", "Charging System (Chinese)"),
    DiagramReference("DT778379", "Load and Four-in-one Sensor (PAHA)"),
    DiagramReference("DT778382", "Battery Management"),
    DiagramReference("DT778383", "Instrument Panel Cluster"),
    DiagramReference("DT778384", "Fuel Pump"),
    DiagramReference("DT778385", "Side Mirror Electric Adjustment"),
    DiagramReference("DT778386", "Engine"),
    DiagramReference("DT778387", "Charging and Distribution Ground"),
    DiagramReference("DT778388", "Side Mirror and Rear Windshield Heating"),
    DiagramReference("DT778389", "Roof Ground"),
    DiagramReference("DT778390", "Rear Bumper Layout"),
    DiagramReference("DT778391", "Electronic Control Subnet"),
    DiagramReference("DT778393", "SRS"),
    DiagramReference("DT778397", "Energy Network"),
    DiagramReference("DT778399", "Smart Access Network"),
    DiagramReference("DT778401", "Blind Spot Detection"),
    DiagramReference("DT778406", "Electronic Injection Subnet"),
    DiagramReference("DT778407", "EPB"),
    DiagramReference("DT778409", "Chassis Network"),
    DiagramReference("DT778410", "Parking Assist"),
    DiagramReference("DT778412", "Body Network"),
    DiagramReference("DT778413", "IPB"),
    DiagramReference("DT778414", "DP-EPS"),
    DiagramReference("DT778416", "ADAS Network"),
    DiagramReference("DT778417", "Gearshift Control"),
    DiagramReference("DT778418", "Rear Drive Motor Control"),
    DiagramReference("DT778430", "Interior Light"),
    DiagramReference("DT778436", "Turn Signal and Warning"),
    DiagramReference("DT778438", "Stop Light"),
    DiagramReference("DT778439", "Roof Wiring Layout"),
    DiagramReference("DT778441", "Fog Light and Reverse Light"),
    DiagramReference("DT778444", "Position Light and DRL"),
    DiagramReference("DT778446", "USB Charging and Backup Power"),
    DiagramReference("DT778448", "Low/High Beam"),
    DiagramReference("DT778450", "Positive Fuse Box System"),
    DiagramReference("DT778451", "Door Lock Motor and Hood Lock"),
    DiagramReference("DT778453", "Window Regulator"),
    DiagramReference("DT778455", "Wiper and Washer"),
    DiagramReference("DT778458", "Instrument Panel Fuse Box"),
    DiagramReference("DT778461", "HUD"),
    DiagramReference("DT778462", "Dual MCU"),
    DiagramReference("DT778464", "Instrument Panel Fuse Box Power"),
]

MODULES = {
    "A01": "ECM",
    "A36": "Dual MCU",
    "BK51": "Battery Pack / BMS",
    "K49": "VCU",
    "KG10": "Airbag Controller",
    "KG64": "Left Domain Control Unit",
    "KG86": "Right Domain Control Unit",
    "Ka76": "Rear Drive Powertrain",
    "Ka31": "Rear Body Controller",
    "G01": "Instrument Panel Cluster",
    "G03": "DLC / OBD2 Port",
    "G07": "Infotainment Unit",
    "G48": "USB Module",
    "G82": "Instrument Panel Fuse Box",
    "G87": "Smart Access Network Terminator",
    "P13": "Multi-purpose Camera",
    "DB40": "Panoramic Front Camera",
    "DB60": "Front mmWave Radar",
    "R06": "Rear Left mmWave Radar",
    "R07": "Rear Right mmWave Radar",
    "K11": "Power Amplifier",
    "K12": "High-frequency Module",
    "K43": "Bidirectional On-board Power Supply",
    "KB46": "Positive Fuse Box",
    "KB77": "CCS Communication Converter",
    "KaB53": "Charging Port Socket",
    "T21": "Smart Access Controller",
    "GaT21": "Interior Smart Access Controller",
    "Ga91": "Wireless Charging Module",
    "PG04": "Four-in-one Sensor",
}


def summary() -> dict[str, Any]:
    return {
        "vehicle": SOURCE["vehicle"],
        "powertrain": SOURCE["powertrain"],
        "source": dict(SOURCE),
        "counts": {
            "harness_codes": len(HARNESS_CODES),
            "wire_colors": len(WIRE_COLORS),
            "network_segments": len(NETWORKS),
            "connector_records": len(CONNECTORS),
            "connector_pin_records": sum(len(item.pins) for item in CONNECTORS.values()),
            "engine_component_records": len(ENGINE_COMPONENTS),
            "ground_points": sum(len(items) for items in GROUND_POINTS.values()),
            "junction_records": len(JUNCTIONS),
            "diagram_records": len(DIAGRAMS),
            "module_records": len(MODULES),
        },
        "machine_executable_fault_injection": False,
        "excluded_operationalization": [
            "voltage glitch sequences",
            "fault-injection target automation",
            "security-access bypass",
            "live vehicle write/flash routines",
        ],
    }


def connector(connector_id: str) -> dict[str, Any] | None:
    item = CONNECTORS.get(connector_id)
    return None if item is None else item.model_dump(mode="json")


def network(name: str) -> dict[str, Any] | None:
    for item in NETWORKS:
        if item.name == name:
            return item.model_dump(mode="json")
    return None


def search_reference(query: str, limit: int = 50) -> list[dict[str, Any]]:
    needle = str(query).strip().lower()
    if not needle:
        return []
    limit = max(1, min(200, int(limit)))
    rows: list[dict[str, Any]] = []

    def add(kind: str, key: str, text: str, payload: dict[str, Any]) -> None:
        if len(rows) >= limit:
            return
        haystack = f"{key} {text}".lower()
        if needle in haystack:
            rows.append({"kind": kind, "key": key, "text": text, "payload": payload})

    for key, item in CONNECTORS.items():
        add("connector", key, item.module, item.model_dump(mode="json"))
        for pin in item.pins:
            add(
                "pin",
                f"{key}:{pin.pin}",
                f"{item.module} {pin.function}",
                {"connector_id": key, "module": item.module, **pin.model_dump(mode="json")},
            )
    for item in NETWORKS:
        add("network", item.name, item.purpose, item.model_dump(mode="json"))
    for key, value in ENGINE_COMPONENTS.items():
        add("engine_component", key, f"{value['component']} {value['functions']}", {"connector_id": key, **value})
    for key, value in MODULES.items():
        add("module", key, value, {"module_id": key, "name": value})
    for item in DIAGRAMS:
        add("diagram", item.diagram_id, item.title, {"diagram_id": item.diagram_id, "title": item.title})
    for category, points in GROUND_POINTS.items():
        for point in points:
            add("ground", point, category, {"ground_id": point, "category": category})
    for code, name in HARNESS_CODES.items():
        add("harness", code, name, {"code": code, "name": name})
    return rows[:limit]
