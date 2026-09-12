from vision_shark.dataplane import SharedMemoryRing
from vision_shark.semantic import SemanticSignalBroker
from vision_shark.sensors import SensorHub
from vision_shark.timebase import TimeAuthority
from vision_shark.autonomy import AutonomyRuntime

def test_shared_memory_overwrite_detection():
 r=SharedMemoryRing(slots=2,slot_bytes=128)
 try:
  a=r.publish(b'a');assert r.read(a).payload==b'a';r.publish(b'b');r.publish(b'c');assert r.read(a) is None
 finally:r.close();r.unlink()
def test_semantic_signal_store():
 b=SemanticSignalBroker();b.publish('Vehicle.Speed',12.5,source='decoder');assert b.get('Vehicle.Speed').value==12.5
def test_sensor_health():
 h=SensorHub();h.register('front','camera');h.observe('front');assert h.health()['front']['healthy']
def test_time_authority():
 t=TimeAuthority();t.observe('camera',1000,2000);t.observe('camera',2000,3000);assert t.health()['camera']['samples']==2
def test_driver_missing_forces_shadow_stop():
 out=AutonomyRuntime().run({'speed':12},driver_observation={'face_detected':False,'eyes_open':False,'gaze_on_road':False,'hands_available':False,'confidence':0});assert out['fallback']['state']=='minimum_risk';assert out['selected']['generator']=='controlled_stop';assert out['live_actuation'] is False
