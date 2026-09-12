import pytest
from vision_shark.domain import Frame
from vision_shark.runtime import Runtime
from vision_shark.storage import RecordingStore


def test_frame_rejects_physically_invalid_classic_and_fd_combinations():
    with pytest.raises(ValueError):Frame(ts_ns=1,bus='can0',arbitration_id=0x800,data='00')
    with pytest.raises(ValueError):Frame(ts_ns=1,bus='can0',arbitration_id=0x123,data='00'*9)
    with pytest.raises(ValueError):Frame(ts_ns=1,bus='can0',arbitration_id=0x123,data='00',brs=True)
    with pytest.raises(ValueError):Frame(ts_ns=1,bus='can0',arbitration_id=0x123,data='',can_fd=True,rtr=True)
    with pytest.raises(ValueError):Frame(ts_ns=1,bus='can0',arbitration_id=0x123,data='00'*10,can_fd=True)
    with pytest.raises(ValueError):Frame(ts_ns=1,bus='can0',arbitration_id=0x123,data='00',rtr=True)
    ok=Frame(ts_ns=1,bus='can0',arbitration_id=0x18DAF110,extended=True,data='00'*12,can_fd=True,brs=True)
    assert ok.can_fd and ok.extended and len(ok.data)==24


def test_recording_drop_completeness_uses_recording_delta(tmp_path):
    store=RecordingStore(tmp_path,commit_every=4,max_commit_interval_s=1)
    runtime=Runtime(store)
    runtime.running=True;runtime.source_kind='socketcan';runtime.interface='can0';runtime.receive_drops=7
    rid=runtime.start_recording({'case':'delta'})
    runtime.ingest(Frame(ts_ns=1,bus='can0',arbitration_id=0x123,data='01'))
    runtime.stop_recording()
    row=next(x for x in store.list_recordings() if x['id']==rid)
    assert row['metadata']['receive_drops_at_start']==7
    assert row['metadata']['receive_drops_at_stop']==7
    assert row['metadata']['receive_drops_during_recording']==0
    assert row['metadata']['capture_complete'] is True
    store.close()


def test_recording_marks_new_drops_incomplete(tmp_path):
    store=RecordingStore(tmp_path,commit_every=4,max_commit_interval_s=1)
    runtime=Runtime(store)
    runtime.running=True;runtime.source_kind='socketcan';runtime.interface='can0';runtime.receive_drops=3
    rid=runtime.start_recording();runtime.receive_drops=5;runtime.stop_recording()
    row=next(x for x in store.list_recordings() if x['id']==rid)
    assert row['metadata']['receive_drops_during_recording']==2
    assert row['metadata']['capture_complete'] is False
    store.close()


def test_storage_batching_preserves_order_and_flushes(tmp_path):
    store=RecordingStore(tmp_path,commit_every=8,max_commit_interval_s=10)
    rid=store.start_recording('import','test',{})
    frames=[Frame(ts_ns=i,bus='can0',arbitration_id=0x100+i,data=f'{i:02x}') for i in range(5)]
    assert store.append_frames(rid,frames)==5
    # load_frames forces a durable flush and sequence order is stable.
    loaded=store.load_frames(rid)
    assert [x.arbitration_id for x in loaded]==[x.arbitration_id for x in frames]
    store.stop_recording(rid)
    meta=store.list_recordings()[0]['metadata']
    assert meta['storage_mode']=='sqlite-wal-batched'
    assert meta['max_uncommitted_frames']==7
    store.close()
