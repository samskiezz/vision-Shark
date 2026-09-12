from __future__ import annotations
import asyncio
from pathlib import Path
from .session import VehicleSession,WorkflowState
from .learning import LearningEngine
from .knowledge import KnowledgeGraph
from .autonomy import AutonomyRuntime
from .adapter_discovery import discover_adapters
from .doip_transport import DoIPReadOnlyClient,DoIPError

class VisionOrchestrator:
    """One-button workflow owner. Engineering primitives stay behind this service."""
    def __init__(self,runtime,knowledge_path=None,audit=None):
        self.runtime=runtime;self.session=VehicleSession();self.learning=LearningEngine();self.audit=audit
        if knowledge_path is None and getattr(runtime,'storage',None) is not None:
            base=getattr(runtime.storage,'path',None)
            if base is not None:knowledge_path=Path(base).parent/'vehicle-knowledge.json'
        self.knowledge=KnowledgeGraph(knowledge_path);self.autonomy=AutonomyRuntime();self._lock=asyncio.Lock();self.diagnostic_endpoint=None;self.diagnostic_proof=None
    def _audit(self,event,payload=None):
        if self.audit:self.audit.append('vision',event,payload or {})
    async def connect_auto(self,simulation=False):
        async with self._lock:
            self.session=VehicleSession(state=WorkflowState.DISCOVERING_HARDWARE);self.session.step('discover_hardware');self.diagnostic_proof=None
            if simulation:
                self.runtime.connect_simulator();self.session.source='simulator';self.session.interface='simulator';self.session.step('simulation_selected');self._audit('simulation_connected')
            else:
                candidates=await asyncio.to_thread(discover_adapters,True,True)
                usable=[c for c in candidates if c.get('usable',True)]
                if not usable:
                    self.session.state=WorkflowState.ERROR;self.session.error='No usable passive CAN/CAN-FD or DoIP/ENET vehicle endpoint detected';self.session.step('discover_hardware','failed');self._audit('connect_failed',{'candidates':candidates});return self.session.snapshot()
                chosen=usable[0];self.session.state=WorkflowState.INITIALISING_INTERFACE;self.session.step('select_adapter',transport=chosen['transport'],interface=chosen['interface'],endpoint=chosen.get('endpoint'));self._audit('adapter_selected',chosen)
                if chosen['transport']=='socketcan':
                    self.runtime.connect_socketcan(chosen['interface']);self.session.source='socketcan';self.session.interface=chosen['interface'];self.diagnostic_endpoint=None
                    self.session.state=WorkflowState.PASSIVE_CAPTURE;self.session.step('passive_capture_started');self._audit('socketcan_passive_capture',{'interface':chosen['interface']})
                elif chosen['transport']=='doip':
                    self.runtime.disconnect();self.session.source='doip';self.session.interface=chosen['interface'];self.diagnostic_endpoint=chosen
                    identity={'status':'doip_discovered','vin':chosen.get('vin'),'logical_address':chosen.get('logical_address'),'endpoint':chosen.get('endpoint'),'eid':chosen.get('eid'),'reason':'ISO 13400 vehicle-identification response'}
                    self.session.vehicle=identity;self.session.confidence=.95;self.knowledge.put('vehicle.doip_identity',identity,.95,'doip-discovery',maturity='observed');self.session.step('doip_vehicle_discovered',endpoint=chosen.get('endpoint'),logical_address=chosen.get('logical_address'))
                    try:
                        proof=await asyncio.to_thread(DoIPReadOnlyClient(chosen['endpoint'],chosen['logical_address']).prove_readonly_session)
                        self.diagnostic_proof=proof;identity['status']='doip_diagnostics_proven';identity['diagnostic_proof']=proof
                        if proof.get('vin') and not identity.get('vin'):identity['vin']=proof['vin']
                        self.session.vehicle=identity;self.session.confidence=.99;self.knowledge.put('vehicle.doip_diagnostic_proof',proof,.99,'doip-readonly-proof',maturity='observed');self.session.step('doip_diagnostics_proven');self._audit('doip_diagnostics_proven',proof)
                    except (DoIPError,OSError,TimeoutError,ValueError) as exc:
                        self.diagnostic_proof={'routing_active':False,'uds_exchange':False,'error':str(exc)};identity['diagnostic_proof']=self.diagnostic_proof
                        self.session.vehicle=identity;self.session.step('doip_discovered_but_diagnostics_unproven','warning');self._audit('doip_diagnostics_unproven',self.diagnostic_proof)
            self.session.state=WorkflowState.READY;return self.session.snapshot()
    async def identify_auto(self,settle_s=.25):
        async with self._lock:
            if self.session.source=='doip' and self.diagnostic_endpoint:return self.session.snapshot()
            if not self.runtime.running:raise ValueError('Connect first')
            self.session.state=WorkflowState.IDENTIFYING_VEHICLE;await asyncio.sleep(max(0.,min(2.,settle_s)));frame_count=len(self.runtime.recent);ids=len({(f.bus,f.arbitration_id) for f in self.runtime.recent})
            identity={'status':'observed_unknown' if self.runtime.source_kind!='simulator' else 'simulation','frame_count':frame_count,'message_ids':ids,'reason':'Exact vehicle identity requires matching evidence'}
            self.session.vehicle=identity;self.session.confidence=0.;self.session.step('vehicle_fingerprint',status=identity['status']);self.knowledge.put('vehicle.identity',identity,0.,'passive-observation');self.session.state=WorkflowState.READY;self._audit('vehicle_identified',identity);return self.session.snapshot()
    async def learn_auto(self):
        async with self._lock:
            if self.session.source=='doip':return {'session':self.session.snapshot(),'report':{'status':'diagnostic_transport','frame_count':0,'message_inventory':[],'signal_hypotheses':[],'reason':'DoIP exposes diagnostics, not a raw CAN frame stream'},'knowledge_digest':self.knowledge.digest()}
            if not self.runtime.running:raise ValueError('Connect first')
            self.session.state=WorkflowState.LEARNING;report=self.learning.analyze(list(self.runtime.recent));self.session.step('passive_learning',frames=report['frame_count'],messages=len(report['message_inventory']),hypotheses=len(report['signal_hypotheses']));self.knowledge.put('learning.latest',report,.5,'passive-learning');self.session.state=WorkflowState.READY;self._audit('passive_learning',{'frames':report['frame_count'],'messages':len(report['message_inventory']),'hypotheses':len(report['signal_hypotheses'])});return {'session':self.session.snapshot(),'report':report,'knowledge_digest':self.knowledge.digest()}
    def shadow_autonomy(self,payload):return self.autonomy.run(**payload)
    def status(self):
        out=self.session.snapshot();out['runtime']=self.runtime.status();out['diagnostic_endpoint']=self.diagnostic_endpoint;out['diagnostic_proof']=self.diagnostic_proof;out['knowledge_digest']=self.knowledge.digest();out['knowledge_facts']=len(self.knowledge.snapshot());return out
