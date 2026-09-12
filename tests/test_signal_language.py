from vision_shark.signal_language import parse_quantity,convert_quantity,SignalEvent,from_j2534,from_doip,classify_event

def test_frequency_and_bitrate_are_dimension_safe():
    assert parse_quantity('500 kbps').as_float()==500_000
    assert parse_quantity('2 MHz').as_float()==2_000_000
    assert convert_quantity('1 GHz','MHz')==1000
    try:convert_quantity('1 GHz','Mbps')
    except ValueError:pass
    else:raise AssertionError('frequency must not be silently treated as bitrate')

def test_vsl_round_trip():
    e=SignalEvent(123,'canfd','data-link','0102','can0',identifier=0x123,metadata={'brs':True})
    assert SignalEvent.decode(e.encode())==e

def test_j2534_iso15765_normalizes_to_transport_layer():
    e=from_j2534(1,b'\x62\xf1\x90VIN',0x06)
    c=classify_event(e)
    assert e.transport=='j2534' and e.layer=='transport'
    assert c['uds_service']==0x62 and c['uds_positive_response']

def test_doip_uds_normalizes_without_changing_payload():
    e=from_doip(2,0x8001,b'\x62\xf1\x90VIN',0x1234,0x0e80,'169.254.1.2')
    c=classify_event(e)
    assert c['uds_service']==0x62
    assert e.metadata['endpoint']=='169.254.1.2'
