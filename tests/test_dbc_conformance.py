import cantools
import pytest
from vision_shark.dbc import parse_database,decode_message
from vision_shark.domain import Frame

SCALAR_DBC='''VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 Example: 8 ECU
 SG_ Speed : 0|16@1+ (0.01,0) [0|655.35] "km/h" ECU
 SG_ Temp : 16|8@1- (1,-40) [-40|215] "C" ECU
 SG_ Torque : 24|16@1- (0.1,0) [-3276.8|3276.7] "Nm" ECU
 SG_ Big : 55|16@0+ (1,0) [0|65535] "" ECU
'''

MUX_DBC='''VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 512 Muxed: 8 ECU
 SG_ Mode M : 0|8@1+ (1,0) [0|255] "" ECU
 SG_ ValueA m1 : 8|16@1+ (0.5,0) [0|32767.5] "" ECU
 SG_ ValueB m2 : 8|16@1+ (2,-10) [-10|131060] "" ECU
'''

EXT_DBC='''VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 2147483939 Extended: 8 ECU
 SG_ X : 0|8@1+ (1,0) [0|255] "" ECU
'''

FD_DBC='''VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 768 FDFrame: 12 ECU
 SG_ Front : 0|16@1+ (1,0) [0|65535] "" ECU
 SG_ Tail : 80|16@1+ (1,0) [0|65535] "" ECU
'''


def _compare(dbc_text,wire_id,payload,frame_id=None,extended=False,can_fd=False):
    ours=parse_database(dbc_text)
    reference=cantools.database.load_string(dbc_text,database_format='dbc',strict=False)
    lookup_id=frame_id if frame_id is not None else wire_id
    expected=reference.decode_message(lookup_id,payload,decode_choices=False,force_extended_id=extended)
    frame=Frame(ts_ns=1,bus='can0',arbitration_id=lookup_id,data=payload.hex(),extended=extended,can_fd=can_fd)
    actual={x['signal']:x['value'] for x in decode_message(ours,frame)}
    assert set(actual)==set(expected)
    for name,value in expected.items():
        assert actual[name]==pytest.approx(value)
    return ours,actual


def test_decoder_matches_cantools_for_signed_little_and_motorola():
    # Speed=12.34; Temp=60; Torque=-12.3; Motorola Big=0x1234.
    payload=bytes.fromhex('d2046485ff001234')
    _,actual=_compare(SCALAR_DBC,256,payload)
    assert actual['Speed']==pytest.approx(12.34)
    assert actual['Temp']==60
    assert actual['Torque']==pytest.approx(-12.3)
    assert actual['Big']==0x1234


def test_decoder_matches_cantools_for_multiplexed_signals():
    payload_a=bytes.fromhex('0164000000000000')
    _,actual_a=_compare(MUX_DBC,512,payload_a)
    assert actual_a['Mode']==1 and actual_a['ValueA']==50
    assert 'ValueB' not in actual_a
    payload_b=bytes.fromhex('020a000000000000')
    _,actual_b=_compare(MUX_DBC,512,payload_b)
    assert actual_b['Mode']==2 and actual_b['ValueB']==10
    assert 'ValueA' not in actual_b


def test_extended_id_is_not_confused_with_standard_id():
    db,actual=_compare(EXT_DBC,2147483939,b'\x2a'+b'\x00'*7,frame_id=0x123,extended=True)
    msg=db['messages'][0]
    assert msg['arbitration_id']==0x123 and msg['extended'] is True
    assert actual['X']==42
    standard=Frame(ts_ns=1,bus='can0',arbitration_id=0x123,data='2a'+'00'*7,extended=False)
    assert decode_message(db,standard)==[]


def test_can_fd_length_and_tail_signal_match_cantools():
    payload=bytes.fromhex('341200000000000000007856')
    db,actual=_compare(FD_DBC,768,payload,can_fd=True)
    assert db['messages'][0]['can_fd'] is True
    assert actual['Front']==0x1234 and actual['Tail']==0x5678


def test_decoder_fails_closed_on_truncated_payload():
    db=parse_database(SCALAR_DBC)
    short=Frame(ts_ns=1,bus='can0',arbitration_id=256,data='00'*7)
    with pytest.raises(ValueError,match='Payload length mismatch'):
        decode_message(db,short)
