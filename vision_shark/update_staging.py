from __future__ import annotations
from pathlib import Path
import hashlib,json,os,tempfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

class SignedArtifactStager:
    """Stages signed application/model/pack artifacts. It does not flash vehicle ECUs."""
    def __init__(self,root:str|Path,public_key_raw:bytes):self.root=Path(root);self.key=Ed25519PublicKey.from_public_bytes(public_key_raw);self.state=self.root/'state.json'
    def stage(self,role,version,payload:bytes,signature:bytes):
        if role not in {'application','model','pack','gateway_firmware'}:raise ValueError('unsupported artifact role')
        version=int(version);digest=hashlib.sha256(payload).hexdigest();message=json.dumps({'role':role,'version':version,'sha256':digest},sort_keys=True,separators=(',',':')).encode();self.key.verify(signature,message)
        state=self._state();current=int(state.get(role,0))
        if version<=current:raise ValueError('rollback or duplicate version rejected')
        target=self.root/role/f'{version}-{digest}.bin';target.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix='.stage-',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
            os.replace(tmp,target)
        finally:
            try:os.unlink(tmp)
            except FileNotFoundError:pass
        state[role]=version;self.root.mkdir(parents=True,exist_ok=True);self.state.write_text(json.dumps(state,sort_keys=True),encoding='utf-8');return {'role':role,'version':version,'sha256':digest,'path':str(target)}
    def _state(self):return json.loads(self.state.read_text()) if self.state.exists() else {}
