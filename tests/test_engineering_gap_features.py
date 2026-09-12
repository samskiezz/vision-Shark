import hashlib,json
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from vision_shark.calibration import CalibrationRegistry
from vision_shark.localization import LocalizationFilter
from vision_shark.model_registry import ProvenanceRegistry
from vision_shark.update_staging import SignedArtifactStager
from vision_shark.agent_facade import ReadOnlyAgentFacade


def test_calibration_persists_and_validates(tmp_path):
    p=tmp_path/'cal.json';r=CalibrationRegistry(p);c=r.put('front_camera','intrinsic',{'fx':1000.,'fy':1001.},source='bench')
    assert len(c.sha256)==64 and CalibrationRegistry(p).get('front_camera') is not None


def test_localisation_fuses_measurement():
    f=LocalizationFilter();f.predict(.1,accel_mps2=1.);before=f.state.position_variance;f.update_gnss(1.,2.,.1)
    assert f.state.source=='gnss_fused' and f.state.position_variance<before


def test_model_registry_binds_dataset_and_evaluation(tmp_path):
    r=ProvenanceRegistry(tmp_path/'models.json');h='a'*64;r.register_dataset('drive-v1',h,'internal',{'train':'b'*64,'val':'c'*64,'test':'d'*64})
    m=r.register_model('perception-v1','e'*64,['drive-v1'],{'mAP':.8})
    assert m['datasets']==['drive-v1'] and r.resolve_model('perception-v1')['evaluation']['mAP']==.8


def test_signed_stager_rejects_rollback(tmp_path):
    private=Ed25519PrivateKey.generate();public=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw);payload=b'model';digest=hashlib.sha256(payload).hexdigest()
    msg=json.dumps({'role':'model','version':1,'sha256':digest},sort_keys=True,separators=(',',':')).encode();s=SignedArtifactStager(tmp_path,public);s.stage('model',1,payload,private.sign(msg))
    with pytest.raises(ValueError):s.stage('model',1,payload,private.sign(msg))


def test_agent_facade_has_no_mutating_tool():
    a=ReadOnlyAgentFacade({'status':lambda:{'ok':True}});assert a.call('status')['ok'];assert a.capabilities()['mutating_tools']==[]
    with pytest.raises(PermissionError):a.call('transmit')
