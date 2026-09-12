import asyncio
from vision_shark.autonomy import AutonomyRuntime
from vision_shark.learning import LearningEngine
from vision_shark.knowledge import KnowledgeGraph
from vision_shark.domain import Frame
from vision_shark.orchestrator import VisionOrchestrator


def test_shadow_never_grants_live_actuation():
    out=AutonomyRuntime().run({'speed':12.0})
    assert out['live_actuation'] is False
    assert out['control_target']['live_actuation_allowed'] is False
    assert out['selected']['points']


def test_shadow_fallback_on_stale_world():
    out=AutonomyRuntime().run({'speed':10.0},sensor_age_s=2.0)
    assert out['odd']['inside'] is False
    assert out['behavior']['mode']=='fallback'
    assert out['selected']['generator']=='controlled_stop'


def test_learning_remains_hypothesis():
    frames=[Frame(ts_ns=i,bus='can0',arbitration_id=0x123,data=f'{i:02x}00') for i in range(4)]
    out=LearningEngine().analyze(frames)
    assert out['status']=='hypotheses_only'
    assert out['signal_hypotheses'][0]['varying_bytes']


def test_knowledge_digest_changes():
    k=KnowledgeGraph();before=k.digest();k.put('x',1,.5,'test');assert k.digest()!=before


class FakeRuntime:
    def __init__(self):self.running=False;self.source_kind=None;self.recent=[]
    def connect_simulator(self):self.running=True;self.source_kind='simulator'
    def connect_socketcan(self,name):self.running=True;self.source_kind='socketcan'
    def status(self):return {'connected':self.running,'source_kind':self.source_kind}


def test_one_button_simulation_path():
    o=VisionOrchestrator(FakeRuntime())
    result=asyncio.run(o.connect_auto(simulation=True))
    assert result['state']=='ready'
    assert result['source']=='simulator'
