from vision_shark.autonomy import AutonomyRuntime
from vision_shark.learning import LearningEngine
from vision_shark.knowledge import KnowledgeGraph
from vision_shark.domain import Frame

def test_shadow_autonomy_never_allows_live_actuation():
    out=AutonomyRuntime().run({'speed':12.0},detections=[])
    assert out['live_actuation'] is False
    assert out['control_target']['live_actuation_allowed'] is False
    assert out['selected']['points']

def test_shadow_fallback_when_world_is_stale():
    out=AutonomyRuntime().run({'speed':10.0},sensor_age_s=2.0)
    assert out['odd']['inside'] is False
    assert out['behavior']['mode']=='fallback'
    assert out['selected']['generator']=='controlled_stop'

def test_learning_is_hypothesis_only():
    frames=[Frame(ts_ns=i,bus='can0',arbitration_id=0x123,data=f'{i:02x}00') for i in range(4)]
    out=LearningEngine().analyze(frames)
    assert out['status']=='hypotheses_only'
    assert out['frame_count']==4
    assert out['signal_hypotheses'][0]['varying_bytes']

def test_knowledge_digest_changes():
    k=KnowledgeGraph();a=k.digest();k.put('x',1,.5,'test');assert k.digest()!=a
