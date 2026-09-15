from __future__ import annotations

import asyncio
from pathlib import Path

from .adapter_discovery import discover_adapters
from .autonomy import AutonomyRuntime
from .autonomy.hybrid import HybridShadowPlanner
from .doip_transport import DoIPError,DoIPReadOnlyClient,parse_uds_response
from .fingerprint import fingerprint_frames
from .knowledge import KnowledgeGraph
from .learning import LearningEngine
from .session import VehicleSession,WorkflowState


class VisionOrchestrator:
    """One-button passive workflow plus explicit read-only diagnostic binding."""
    def __init__(self,runtime,knowledge_path=None,audit=None):
        self.runtime=runtime;self.session=VehicleSession();self.learning=LearningEngine();self.audit=audit
        if knowledge_path is None and getattr(runtime,'storage',None) is not None:
            base=getattr(runtime.storage,'path',None)
            if base is not None:knowledge_path=Path(base).parent/'vehicle-knowledge.json'
        self.knowledge=KnowledgeGraph(knowledge_path);self.autonomy=AutonomyRuntime();self.hybrid_autonomy=HybridShadowPlanner();self._lock=asyncio.Lock();self.diagnostic_endpoint=None;self.diagnostic_proof=None

    def _audit(self,event,payload=None):
        if self.audit:self.audit.append('vision',event,payload or {})

    async def connect_auto(self,simulation=False):
        """Connect without transmitting discovery traffic.

        Automatic connect selects simulator or a driver-reported passive SocketCAN
        interface only. DoIP/ENET discovery is a separate explicit audited action.
        """
        async with self._lock:
            self.session=VehicleSession(state=WorkflowState.DISCOVERING_HARDWARE);self.session.step('discover_hardware');self.diagnostic_endpoint=None;self.diagnostic_proof=None
            if simulation:
                self.runtime.connect_simulator();self.session.source='simulator';self.session.interface='simulator';self.session.step('simulation_selected');self._audit('simulation_connected');self.session.state=WorkflowState.READY;return self.session.snapshot()
            candidates=await asyncio.to_thread(discover_adapters,False,True)
            usable=[c for c in candidates if c.get('usable',True) and c.get('transport')=='socketcan']
            if not usable:
                detected=[{'transport':c.get('transport'),'interface':c.get('interface'),'detail':c.get('detail')} for c in candidates]
                self.session.state=WorkflowState.ERROR;self.session.error='No passive SocketCAN interface detected. ENET/DoIP discovery requires the explicit discovery action.';self.session.step('discover_hardware','failed');self._audit('connect_failed',{'detected':detected,'doip_discovery_attempted':False});return self.session.snapshot()
            chosen=usable[0];self.session.state=WorkflowState.INITIALISING_INTERFACE;self.session.step('select_adapter',transport='socketcan',interface=chosen['interface']);self.runtime.connect_socketcan(chosen['interface']);self.session.source='socketcan';self.session.interface=chosen['interface'];self.session.state=WorkflowState.PASSIVE_CAPTURE;self.session.step('passive_capture_started');self._audit('socketcan_passive_capture',{'interface':chosen['interface']});self.session.state=WorkflowState.READY;return self.session.snapshot()

    async def connect_doip_endpoint(self,endpoint:str,logical_address:int,interface:str='ethernet',discovery_vin:str|None=None,eid:str|None=None,metadata:dict|None=None):
        """Explicitly bind and prove a read-only DoIP diagnostic endpoint.

        A VIN learned only from unauthenticated UDP discovery is retained as untrusted
        metadata and is never promoted to vehicle identity evidence. A routed UDS
        exchange is required before diagnostics_read becomes true.
        """
        async with self._lock:
            logical=int(logical_address)
            if not endpoint or not 0<=logical<=0xffff:raise ValueError('valid DoIP endpoint and logical address are required')
            self.runtime.disconnect();self.session=VehicleSession(state=WorkflowState.INITIALISING_INTERFACE);self.session.source='doip';self.session.interface=str(interface or 'ethernet')
            self.diagnostic_endpoint={'transport':'doip','interface':self.session.interface,'endpoint':str(endpoint),'logical_address':logical,'eid':eid,'metadata':dict(metadata or {}),'discovery_vin_untrusted':discovery_vin}
            self.session.step('doip_endpoint_selected',endpoint=endpoint,logical_address=logical);self._audit('doip_endpoint_selected',{'endpoint':endpoint,'logical_address':logical,'discovery_vin_present':bool(discovery_vin)})
            try:proof=await asyncio.to_thread(DoIPReadOnlyClient(str(endpoint),logical).prove_readonly_session)
            except (DoIPError,OSError,TimeoutError,ValueError) as exc:
                self.diagnostic_proof={'routing_active':False,'uds_exchange':False,'error':str(exc)};self.session.state=WorkflowState.ERROR;self.session.error='Routed DoIP diagnostics could not be proven';self.session.step('doip_diagnostics_unproven','failed');self._audit('doip_diagnostics_unproven',self.diagnostic_proof);return self.session.snapshot()
            self.diagnostic_proof=proof;identity={'status':'doip_diagnostics_proven','vin':proof.get('vin'),'logical_address':logical,'endpoint':str(endpoint),'eid':eid,'reason':'routed read-only UDS exchange proven','discovery_vin_untrusted':discovery_vin}
            self.session.vehicle=identity;self.session.confidence=.99 if proof.get('vin') else .80;self.session.capabilities['diagnostics_read']=True;self.session.state=WorkflowState.READY;self.session.step('doip_diagnostics_proven',latency_ms=proof.get('latency_ms'));self.knowledge.put('vehicle.doip_diagnostic_proof',proof,.99,'doip-readonly-proof',maturity='observed')
            if proof.get('vin'):self.knowledge.put('vehicle.doip_identity',identity,.99,'doip-readonly-proof',maturity='observed')
            self._audit('doip_diagnostics_proven',{'endpoint':endpoint,'logical_address':logical,'vin_proven':bool(proof.get('vin')),'latency_ms':proof.get('latency_ms')});return self.session.snapshot()

    async def disconnect_auto(self):
        async with self._lock:
            prior_source=self.session.source;prior_endpoint=self.diagnostic_endpoint;self.runtime.disconnect();self.session=VehicleSession();self.diagnostic_endpoint=None;self.diagnostic_proof=None;self._audit('disconnected',{'source':prior_source,'endpoint':None if not prior_endpoint else prior_endpoint.get('endpoint')});return self.status()

    async def identify_auto(self,settle_s=.25):
        async with self._lock:
            if self.session.source=='doip' and self.diagnostic_endpoint:return self.session.snapshot()
            if not self.runtime.running:raise ValueError('Connect first')
            self.session.state=WorkflowState.IDENTIFYING_VEHICLE;await asyncio.sleep(max(0.,min(2.,settle_s)));frames=list(self.runtime.recent);fingerprint=fingerprint_frames(frames)
            identity={'status':'observed_unknown' if self.runtime.source_kind!='simulator' else 'simulation','frame_count':fingerprint['frame_count'],'message_ids':fingerprint['message_count'],'fingerprint_sha256':fingerprint['sha256'],'reason':'Structural fingerprint observed; exact vehicle identity requires a vehicle-specific evidence match'}
            self.session.vehicle=identity;self.session.confidence=0.;self.session.step('vehicle_fingerprint',status=identity['status'],sha256=fingerprint['sha256']);self.knowledge.put('vehicle.identity',identity,0.,'passive-observation');self.knowledge.put('vehicle.fingerprint',fingerprint,.99,'passive-structure',maturity='observed');self.session.state=WorkflowState.READY;self._audit('vehicle_fingerprint',{'sha256':fingerprint['sha256'],'frames':fingerprint['frame_count'],'messages':fingerprint['message_count']});return self.session.snapshot()

    def _require_doip(self):
        if self.session.source!='doip' or not self.diagnostic_endpoint or not self.diagnostic_proof or not self.diagnostic_proof.get('uds_exchange'):raise ValueError('A proven DoIP diagnostic connection is required')

    async def read_doip_dids(self,dids:list[int]):
        async with self._lock:
            self._require_doip();clean=[]
            for did in dids:
                value=int(did)
                if not 0<=value<=0xffff:raise ValueError('DID out of range')
                if value not in clean:clean.append(value)
            if not clean or len(clean)>16:raise ValueError('Request 1 to 16 DIDs')
            endpoint=self.diagnostic_endpoint
            def read_once():
                with DoIPReadOnlyClient(endpoint['endpoint'],endpoint['logical_address']) as client:return client.read_dids(clean)
            raw=await asyncio.to_thread(read_once);parsed=parse_uds_response(raw,0x22);result={'dids':[f'{x:04X}' for x in clean],'response':parsed};self._audit('doip_read_dids',{'dids':result['dids'],'response_kind':parsed.get('kind'),'ok':parsed.get('ok')});return result

    async def read_doip_dtcs(self,status_mask:int=0xff):
        async with self._lock:
            self._require_doip();mask=int(status_mask)
            if not 0<=mask<=0xff:raise ValueError('DTC status mask out of range')
            endpoint=self.diagnostic_endpoint
            def read_once():
                with DoIPReadOnlyClient(endpoint['endpoint'],endpoint['logical_address']) as client:return client.read_dtcs(mask)
            raw=await asyncio.to_thread(read_once);parsed=parse_uds_response(raw,0x19);result={'status_mask':mask,'response':parsed};self._audit('doip_read_dtcs',{'status_mask':mask,'response_kind':parsed.get('kind'),'ok':parsed.get('ok')});return result

    async def learn_auto(self):
        async with self._lock:
            if self.session.source=='doip':return {'session':self.session.snapshot(),'report':{'status':'diagnostic_transport','frame_count':0,'message_inventory':[],'signal_hypotheses':[],'reason':'DoIP is a diagnostic transport, not a raw CAN frame stream'},'knowledge_digest':self.knowledge.digest()}
            if not self.runtime.running:raise ValueError('Connect first')
            self.session.state=WorkflowState.LEARNING;report=self.learning.analyze(list(self.runtime.recent));self.session.step('passive_learning',frames=report['frame_count'],messages=len(report['message_inventory']),hypotheses=len(report['signal_hypotheses']));self.knowledge.put('learning.latest',report,.5,'passive-learning');self.session.state=WorkflowState.READY;self._audit('passive_learning',{'frames':report['frame_count'],'messages':len(report['message_inventory']),'hypotheses':len(report['signal_hypotheses'])});return {'session':self.session.snapshot(),'report':report,'knowledge_digest':self.knowledge.digest()}

    def shadow_autonomy(self,payload):return self.autonomy.run(**payload)
    def hybrid_shadow_autonomy(self,payload):
        result=self.hybrid_autonomy.run(**payload)
        self._audit('hybrid_shadow_autonomy',{'selected':result['selected']['generator'],'risk':result['risk']['risk'],'odd_inside':result['odd']['inside']})
        return result
    def status(self):
        out=self.session.snapshot();out['runtime']=self.runtime.status();out['diagnostic_endpoint']=self.diagnostic_endpoint;out['diagnostic_proof']=self.diagnostic_proof;out['knowledge_digest']=self.knowledge.digest();out['knowledge_facts']=len(self.knowledge.snapshot());return out
