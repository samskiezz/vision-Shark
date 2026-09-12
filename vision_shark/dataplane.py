from __future__ import annotations
import struct,time
from dataclasses import dataclass
from multiprocessing import shared_memory
_HEADER=struct.Struct('<QQII')
@dataclass(frozen=True)
class DataPlaneSample:sequence:int;timestamp_ns:int;payload:bytes;flags:int=0
class SharedMemoryRing:
 def __init__(self,name=None,slots=64,slot_bytes=262144,create=True):
  if slots<2 or slot_bytes<=_HEADER.size:raise ValueError('invalid ring geometry')
  self.slots=slots;self.slot_bytes=slot_bytes;self.payload_bytes=slot_bytes-_HEADER.size;self.shm=shared_memory.SharedMemory(name=name,create=create,size=slots*slot_bytes if create else 0);self.name=self.shm.name;self._seq=0
  if create:self.shm.buf[:]=b'\0'*len(self.shm.buf)
 def publish(self,payload,timestamp_ns=None,flags=0):
  if len(payload)>self.payload_bytes:raise ValueError('payload exceeds slot capacity')
  self._seq+=1;seq=self._seq;off=(seq%self.slots)*self.slot_bytes;ts=time.monotonic_ns() if timestamp_ns is None else int(timestamp_ns);self.shm.buf[off+_HEADER.size:off+_HEADER.size+len(payload)]=payload;self.shm.buf[off:off+_HEADER.size]=_HEADER.pack(seq,ts,len(payload),int(flags));return seq
 def read(self,sequence):
  if sequence<=0:return None
  off=(sequence%self.slots)*self.slot_bytes;seq,ts,n,flags=_HEADER.unpack(bytes(self.shm.buf[off:off+_HEADER.size]))
  if seq!=sequence or n>self.payload_bytes:return None
  payload=bytes(self.shm.buf[off+_HEADER.size:off+_HEADER.size+n]);seq2=_HEADER.unpack(bytes(self.shm.buf[off:off+_HEADER.size]))[0];return DataPlaneSample(seq,ts,payload,flags) if seq2==seq else None
 def close(self):self.shm.close()
 def unlink(self):self.shm.unlink()
