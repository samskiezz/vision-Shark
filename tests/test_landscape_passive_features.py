from fastapi.testclient import TestClient

from vision_shark.anomaly import compare_anomaly
from vision_shark.api import create_app
from vision_shark.domain import Frame
from vision_shark.ecu_fingerprint import ecu_clock_hypotheses
from vision_shark.event_diff import event_bit_diff
from vision_shark.sniffer import sniffer_view
from vision_shark.trace_import import parse_asc,parse_trc
from vision_shark.uds_reference import reference


def frame(ts,aid,data,bus='can0'):
    return Frame(ts_ns=ts,bus=bus,arbitration_id=aid,data=data)


def test_sniffer_view_tracks_byte_changes():
    rows=[frame(0,0x100,'0001'),frame(10_000_000,0x100,'0101'),frame(20_000_000,0x100,'0102')]
    view=sniffer_view(rows,changed_only=True,changed_within_ms=25)
    assert view['message_count']==1
    message=view['messages'][0]
    assert message['latest_data']=='0102'
    assert message['bytes'][0]['change_count']==1
    assert message['bytes'][1]['change_count']==1


def test_event_diff_finds_bit_moving_with_events():
    rows=[]
    for i in range(20):
        ts=i*100_000_000
        value=1 if i in (9,11) else 0
        rows.append(frame(ts,0x123,f'{value:02x}'))
    report=event_bit_diff(rows,[{'ts_ns':1_000_000_000,'label':'button'}],250)
    assert report['status']=='hypotheses_only'
    assert any(x['arbitration_id']==0x123 and x['bit']==0 and x['score']>0 for x in report['candidates'])


def test_anomaly_baseline_detects_new_missing_and_rate_shift():
    baseline=[];observed=[]
    for i in range(20):
        baseline.append(frame(i*100_000_000,0x100,'00'))
        baseline.append(frame(i*100_000_000,0x200,'11'))
    for i in range(20):
        observed.append(frame(i*40_000_000,0x100,'00'))
        observed.append(frame(i*40_000_000,0x300,'22'))
    findings=compare_anomaly(baseline,observed)['findings']
    kinds={(x['arbitration_id'],x['kind']) for x in findings}
    assert (0x200,'missing_identifier') in kinds
    assert (0x300,'new_identifier') in kinds
    assert (0x100,'rate_shift') in kinds


def test_ecu_clusters_group_identifiers_by_skew():
    rows=[]
    for i in range(12):
        rows.append(frame(i*10_001_000,0x100,'00'))
        rows.append(frame(i*10_001_500,0x101,'00'))
    result=ecu_clock_hypotheses(rows,tolerance_ppm=100)
    assert result['identifier_count']==2
    assert result['clusters']
    assert result['status']=='ecu_membership_hypotheses_only'


def test_asc_and_trc_import_parse_classic_rtr_and_fd():
    asc='0.000000 1 123 Rx d 2 01 02\n0.010000 1 456x Rx r 0\n'
    a=parse_asc(asc)
    assert a[0].arbitration_id==0x123 and a[0].data=='0102'
    assert a[1].rtr is True and a[1].extended is True
    trc='1) 0.000000 Rx 123 DT 2 01 02\n2) 0.010000 Rx 18DAF110 FD 3 AA BB CC\n3) 0.020000 Rx 456 RTR 0\n'
    t=parse_trc(trc)
    assert t[1].can_fd is True and t[1].extended is True
    assert t[2].rtr is True


def test_uds_reference_contains_standard_vin_and_nrc():
    data=reference()
    assert data['dids']['F190']=='Vehicle identification number'
    assert data['negative_response_codes']['31']=='requestOutOfRange'


def test_research_routes_and_discovery_are_nontransmitting_by_default(monkeypatch,tmp_path):
    import vision_shark.research_api as research
    calls=[]
    monkeypatch.setattr(research,'discover_adapters',lambda include_doip,include_j2534:calls.append((include_doip,include_j2534)) or [])
    with TestClient(create_app(tmp_path)) as client:
        discovery=client.post('/api/discovery/adapters',json={'include_doip':False,'include_j2534':True})
        assert discovery.status_code==200 and calls==[(False,True)]
        assert discovery.json()['doip_broadcast_transmitted'] is False
        denied=client.post('/api/discovery/adapters',json={'include_doip':True,'include_j2534':False})
        assert denied.status_code==403
        uds=client.get('/api/reference/uds')
        assert uds.status_code==200 and 'F190' in uds.json()['dids']


def test_trace_import_and_recording_analysis_api(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        asc='0.000000 1 123 Rx d 1 00\n0.010000 1 123 Rx d 1 01\n0.020000 1 123 Rx d 1 00\n'
        imported=client.post('/api/import/trace',json={'format':'asc','content':asc,'metadata':{'source':'test'}})
        assert imported.status_code==200 and imported.json()['frames']==3
        rid=imported.json()['recording_id']
        event=client.post(f'/api/recordings/{rid}/event-diff',json={'events':[{'ts_ns':10_000_000,'label':'toggle'}],'window_ms':15})
        assert event.status_code==200
        clusters=client.get(f'/api/recordings/{rid}/ecu-clusters')
        assert clusters.status_code==200
