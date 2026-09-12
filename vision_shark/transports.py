"""Receive-only transport layer. There is deliberately no raw CAN send method."""
import json,math,re,socket,struct,subprocess,sys,time,random
from .domain import Frame
CAN_EFF_FLAG=0x80000000;CAN_RTR_FLAG=0x40000000;CAN_ERR_FLAG=0x20000000;CAN_RAW_FD_FRAMES=5;SOL_CAN_RAW=101
SO_RXQ_OVFL=getattr(socket,'SO_RXQ_OVFL',40);SO_TIMESTAMPNS=getattr(socket,'SO_TIMESTAMPNS',35)

def interface_details(interface):
 if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}',interface):raise ValueError('Invalid interface name')
 if sys.platform!='linux':raise RuntimeError('Live SocketCAN requires Linux')
 r=subprocess.run(['ip','-details','-json','link','show','dev',interface],capture_output=True,text=True,timeout=3,check=True);rows=json.loads(r.stdout)
 if not rows:raise RuntimeError('Interface does not exist')
 return rows[0]
def require_passive(details,allow_vcan=False):
 info=details.get('linkinfo',{});kind=info.get('info_kind')
 if kind=='vcan' and allow_vcan:return 'virtual bench network'
 if kind!='can':raise ValueError('Interface is not physical CAN')
 if 'UP' not in details.get('flags',[]):raise ValueError('CAN interface is down')
 ctrl=info.get('info_data',{}).get('ctrlmode',[]);flags=ctrl.get('flags',[]) if isinstance(ctrl,dict) else ctrl
 if isinstance(flags,str):flags=flags.split(',')
 if 'LISTEN-ONLY' not in {str(x).upper().replace('_','-') for x in flags}:raise PermissionError('Live capture requires driver-reported LISTEN-ONLY mode')
 return 'driver-reported listen-only'
def list_can_interfaces(allow_vcan=False):
 if sys.platform!='linux':return []
 try:rows=json.loads(subprocess.run(['ip','-details','-json','link','show'],capture_output=True,text=True,timeout=3,check=True).stdout)
 except Exception:return []
 out=[]
 for row in rows:
  info=row.get('linkinfo',{});kind=info.get('info_kind')
  if kind not in ('can','vcan'):continue
  ctrl=info.get('info_data',{}).get('ctrlmode',[]);flags=ctrl.get('flags',[]) if isinstance(ctrl,dict) else ctrl
  if isinstance(flags,str):flags=flags.split(',')
  flags={str(x).upper().replace('_','-') for x in (flags or [])};out.append({'name':row.get('ifname',''),'kind':kind,'up':'UP' in row.get('flags',[]),'passive_eligible':(kind=='can' and 'LISTEN-ONLY' in flags) or (kind=='vcan' and allow_vcan),'ctrlmode':sorted(flags)})
 return out
class SimulationSource:
 def __init__(self,seed=1):self.step=0;self.base=time.monotonic_ns();self.dropped=0;self.rng=random.Random(seed)
 def open(self):return None
 def read_batch(self):
  time.sleep(.05);self.step+=1;t=self.step*.05;speed=max(0,48+18*math.sin(t/10));data=struct.pack('<HhBBBB',round(speed*100),0,self.step%16,0,0,0);return [Frame(ts_ns=self.base+self.step*50_000_000,bus='sim0',arbitration_id=0x601,data=data.hex())]
 def read(self,timeout=.25):return self.read_batch()[0]
 def close(self):return None
SimulatorSource=SimulationSource
class SocketCanSource:
 def __init__(self,interface,allow_vcan=False):self.interface=interface;self.details=interface_details(interface);self.assurance=require_passive(self.details,allow_vcan);self.dropped=0;self.sock=None;self._last_overflow=0;self._open()
 def _open(self):
  self.sock=socket.socket(socket.AF_CAN,socket.SOCK_RAW,socket.CAN_RAW);self.sock.setsockopt(SOL_CAN_RAW,CAN_RAW_FD_FRAMES,1);self.sock.setsockopt(socket.SOL_SOCKET,SO_RXQ_OVFL,1)
  try:self.sock.setsockopt(socket.SOL_SOCKET,SO_TIMESTAMPNS,1)
  except OSError:pass
  self.sock.settimeout(.15);self.sock.bind((self.interface,))
 def open(self):return None
 def read_batch(self):
  raw,anc,_,_=self.sock.recvmsg(72,128);ts_ns=time.monotonic_ns()
  for level,ctype,data in anc:
   if level==socket.SOL_SOCKET and ctype==SO_RXQ_OVFL and len(data)>=4:
    total=struct.unpack('=I',data[:4])[0];delta=(total-self._last_overflow)&0xffffffff;self.dropped+=delta;self._last_overflow=total
   elif level==socket.SOL_SOCKET and ctype==SO_TIMESTAMPNS and len(data)>=16:
    sec,nsec=struct.unpack('=qq',data[:16]);ts_ns=sec*1_000_000_000+nsec
  can_id,length,flags,_,_=struct.unpack('=IBBBB',raw[:8]);fd=len(raw)==72;rtr=bool(can_id&CAN_RTR_FLAG)
  return [Frame(ts_ns=ts_ns,bus=self.interface,arbitration_id=can_id&0x1fffffff,data='' if rtr else raw[8:8+length].hex(),can_fd=fd,extended=bool(can_id&CAN_EFF_FLAG),rtr=rtr,error=bool(can_id&CAN_ERR_FLAG),brs=fd and bool(flags&1),esi=fd and bool(flags&2))]
 def read(self,timeout=.25):
  self.sock.settimeout(timeout)
  try:return self.read_batch()[0]
  except socket.timeout:return None
 def close(self):
  if self.sock:self.sock.close();self.sock=None
SocketCANSource=SocketCanSource
