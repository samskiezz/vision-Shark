import hashlib,json
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from vision_shark.calibration import CalibrationRegistry
from vision_shark.localization import LocalizationFilter
from vision_shark.model_registry import ProvenanceRegistry
from vision_shark.update_staging import SignedArtifactStager
from vision_shark.agent_facade import ReadOnlyAgentFacade


def test_calibration_and_localization(tmp_path):
    r=CalibrationRegistry(tmp_path/'cal.json');c=r.put('cam0','camera',{'fx':900.,'fy':901.},'camera','vehicle')
    assert r.get('cam0').sha256==c.sha256
    f=LocalizationFilter();f.update_gnss(10,5,.1);before=f.state.position_variance;f.predict(.1,accel_mps2=1);assert f.state.position_variance>=before


def test_dataset_model_provenance_is_immutable(tmp_path):
    r=ProvenanceRegistry(tmp_path/'registry.json');a='a'*64;b='b'*64
    r.register_dataset('drive-v1',a,'internal',{'train':a,'test':b})
    r.register_model('perception-v1',b,['drive-v1'],{'mAP':.5})
    assert r.resolve_model('perception-v1')['datasets']==['drive-v1']
    with pytest.raises(ValueError):r.register_model('perception-v1',b,['drive-v1'],{})


def test_signed_stager_rejects_rollback(tmp_path):
    private=Ed25519PrivateKey.generate();public=private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw);payload=b'model';digest=hashlib.sha256(payload).hexdigest();msg=json.dumps({'role':'model','version':2,'sha256':digest},sort_keys=True,separators=(',',':')).encode();sig=private.sign(msg)
    s=SignedArtifactStager(tmp_path,public);assert s.stage('model',2,payload,sig)['version']==2
    with pytest.raises(ValueError):s.stage('model',2,payload,sig)


def test_agent_facade_has_no_mutation_path():
    a=ReadOnlyAgentFacade({'status':lambda:{'ok':True}});assert a.call('status')['ok'];assert a.capabilities()['vehicle_tx'] is False
    with pytest.raises(PermissionError):a.call('transmit')
    with pytest.raises(ValueError):ReadOnlyAgentFacade({'connect':lambda:None})
