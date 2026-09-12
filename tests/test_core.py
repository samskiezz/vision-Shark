from fastapi.testclient import TestClient
from vision_shark.api import create_app
from vision_shark.dbc import parse_database,decode_message
from vision_shark.domain import Frame

def test_health_and_transmit_boundary():
 c=TestClient(create_app());assert c.get('/health').status_code==200;assert c.post('/api/transmit').status_code==403

def test_simulator_is_explicit():
 c=TestClient(create_app());r=c.post('/api/connect',json={'source':'simulation'});assert r.status_code==200 and r.json()['simulated'] is True;c.post('/api/disconnect')

def test_dbc_decode():
 db=parse_database('BO_ 291 TEST: 8 Vector__XXX\n SG_ Speed : 0|16@1+ (0.01,0) [0|655.35] "km/h" Vector__XXX')
 f=Frame(ts_ns=1,bus='can0',arbitration_id=291,data='1027000000000000');v=decode_message(db,f);assert v[0]['signal']=='Speed' and v[0]['value']==100.0

def test_bad_dbc_rejected():
 import pytest
 with pytest.raises(ValueError):parse_database('not a database')
