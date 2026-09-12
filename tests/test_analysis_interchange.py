from fastapi.testclient import TestClient
from vision_shark.api import create_app
from vision_shark.domain import Frame
from vision_shark.fingerprint import fingerprint_frames,compare_fingerprints
from vision_shark.interchange import parse_candump,export_candump,parse_csv,export_csv,parse_jsonl,export_jsonl
from vision_shark.isotp_passive import PassiveIsoTpAssembler


def frame(ts,arb,data,bus='can0',fd=False,brs=False,extended=False,rtr=False):
    return Frame(ts_ns=ts,bus=bus,arbitration_id=arb,data=data,can_fd=fd,brs=brs,extended=extended,rtr=rtr)


def test_fingerprint_is_deterministic_and_fuzzy():
    frames=[frame(1,0x100,'0102'),frame(1_000_001,0x100,'0304'),frame(2_000_001,0x200,'00')]
    a=fingerprint_frames(frames);b=fingerprint_frames(list(reversed(frames)))
    assert a['sha256']==b['sha256'] and a['message_count']==2
    observed=fingerprint_frames(frames+[frame(3_000_001,0x300,'0000')])
    match=compare_fingerprints(observed,a)
    assert match['score']==1.0 and match['observed_extra']==1


def test_passive_isotp_single_and_multiframe():
    asm=PassiveIsoTpAssembler()
    one=asm.consume(frame(1,0x7e8,'037f2231'))
    assert len(one)==1 and one[0].payload_hex=='7f2231' and one[0].complete
    assert asm.consume(frame(2,0x7e8,'100a62f190313233'))==[]
    multi=asm.consume(frame(3,0x7e8,'2134353637'))
    assert len(multi)==1 and multi[0].payload_hex=='62f19031323334353637' and multi[0].frame_count==2


def test_passive_isotp_new_transaction_discards_stale_stream():
    asm=PassiveIsoTpAssembler()
    assert asm.consume(frame(1,0x7e8,'100a62f190313233'))==[]
    result=asm.consume(frame(2,0x7e8,'037f2231'))
    assert len(result)==2
    assert result[0].complete is False and result[0].reason=='superseded_by_single_frame'
    assert result[1].complete is True and result[1].payload_hex=='7f2231'
    assert asm.consume(frame(3,0x7e8,'2134353637'))==[]


def test_passive_isotp_extended_addressing_single_and_multiframe():
    asm=PassiveIsoTpAssembler(addressing='extended',address_extension=0xf1)
    one=asm.consume(frame(1,0x700,'f1037f2231'))
    assert len(one)==1 and one[0].payload_hex=='7f2231' and one[0].address_extension==0xf1 and one[0].addressing=='extended'
    assert asm.consume(frame(2,0x700,'f1100962f1903132'))==[]
    multi=asm.consume(frame(3,0x700,'f1213334353637'))
    assert len(multi)==1 and multi[0].payload_hex=='62f190313233343536' and multi[0].frame_count==2
    assert asm.consume(frame(4,0x700,'f203010203'))==[]


def test_passive_isotp_extended_addressing_separates_extensions():
    asm=PassiveIsoTpAssembler(addressing='extended')
    assert asm.consume(frame(1,0x700,'f1100962f1903132'))==[]
    assert asm.consume(frame(2,0x700,'f2100962f1914142'))==[]
    first=asm.consume(frame(3,0x700,'f1213334353637'))
    second=asm.consume(frame(4,0x700,'f2214344454647'))
    assert first[0].address_extension==0xf1 and first[0].payload_hex.startswith('62f190')
    assert second[0].address_extension==0xf2 and second[0].payload_hex.startswith('62f191')


def test_passive_isotp_sequence_mismatch_fails_closed():
    asm=PassiveIsoTpAssembler();assert asm.consume(frame(1,0x7e8,'100a62f190313233'))==[]
    result=asm.consume(frame(2,0x7e8,'2234353637'))
    assert result[0].complete is False and result[0].reason=='sequence_mismatch'


def test_candump_csv_jsonl_roundtrip():
    original=[frame(1_000_000_000,0x123,'0102'),frame(2_000_000_000,0x18daf110,'aabbcc',fd=True,brs=True,extended=True)]
    candump=export_candump(original);parsed=parse_candump(candump)
    assert [(x.arbitration_id,x.data,x.can_fd,x.brs,x.extended) for x in parsed]==[(x.arbitration_id,x.data,x.can_fd,x.brs,x.extended) for x in original]
    assert [x.model_dump() for x in parse_csv(export_csv(original))]==[x.model_dump() for x in original]
    assert [x.model_dump() for x in parse_jsonl(export_jsonl(original))]==[x.model_dump() for x in original]


def test_candump_preserves_exact_nanoseconds_and_rtr():
    text='(1757685234.123456789) can0 123#R\n'
    parsed=parse_candump(text)
    assert parsed[0].ts_ns==1_757_685_234_123_456_789
    assert parsed[0].rtr is True and parsed[0].data==''
    exported=export_candump(parsed)
    assert '(1757685234.123456789)' in exported and '123#R' in exported
    roundtrip=parse_candump(exported)[0]
    assert roundtrip.ts_ns==parsed[0].ts_ns and roundtrip.rtr is True


def test_candump_preserves_low_valued_extended_identifier():
    original=frame(1_000_000_000,0x123,'aa',extended=True)
    text=export_candump([original])
    assert '00000123#AA' in text
    parsed=parse_candump(text)[0]
    assert parsed.arbitration_id==0x123 and parsed.extended is True


def test_interchange_and_health_http(tmp_path):
    c=TestClient(create_app(tmp_path))
    capture='(1.000000000) can0 123#0102\n(1.100000000) can0 123#0304\n'
    imported=c.post('/api/interchange/import',json={'format':'candump','content':capture,'metadata':{'source':'test'}})
    assert imported.status_code==200 and imported.json()['frames']==2
    rid=imported.json()['recording_id']
    exported=c.get(f'/api/recordings/{rid}/export?format=candump')
    assert exported.status_code==200 and '123#0102' in exported.text
    fp=c.get(f'/api/recordings/{rid}/fingerprint')
    assert fp.status_code==200 and fp.json()['message_count']==1
    health=c.get('/api/system/health')
    assert health.status_code==200 and health.json()['status'] in ('ok','degraded') and health.json()['live_actuation'] is False
