import cantools
from vision_shark.dbc import parse_database,decode_message
from vision_shark.domain import Frame

DBC='''VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 Example: 8 ECU
 SG_ Speed : 0|16@1+ (0.01,0) [0|655.35] "km/h" ECU
 SG_ Temp : 16|8@1- (1,-40) [-40|215] "C" ECU
'''

def test_decoder_matches_cantools_for_supported_scalar_subset():
    ours=parse_database(DBC);reference=cantools.database.load_string(DBC,database_format='dbc',strict=False);payload=bytes.fromhex('d204640000000000')
    expected=reference.decode_message(256,payload,decode_choices=False);frame=Frame(ts_ns=1,bus='can0',arbitration_id=256,data=payload.hex());actual={x['signal']:x['value'] for x in decode_message(ours,frame)}
    assert actual['Speed']==expected['Speed']==12.34
    assert actual['Temp']==expected['Temp']==60
