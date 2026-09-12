from __future__ import annotations

from .dbc import decode_message
from .domain import Frame

_SPEED_NAMES={'speed','vehicle_speed','vehiclespeed','veh_speed','road_speed'}
_CHARGE_NAMES={'charge_power','charging_power','charger_power','dc_charge_power','ac_charge_power'}

def _norm(name:str)->str:return ''.join(ch.lower() if ch.isalnum() else '_' for ch in str(name)).strip('_')

def segment_recording(frames:list[Frame],database:dict)->dict:
    samples=[];last_speed=0.0;last_charge=0.0
    for frame in sorted(frames,key=lambda f:int(f.ts_ns)):
        try:values=decode_message(database,frame)
        except ValueError:continue
        touched=False
        for value in values:
            name=_norm(value.get('signal',''))
            numeric=value.get('value')
            if numeric is None:continue
            if name in _SPEED_NAMES or name.endswith('_vehicle_speed'):
                last_speed=float(numeric);touched=True
            if name in _CHARGE_NAMES or ('charge' in name and 'power' in name):
                last_charge=float(numeric);touched=True
        if touched:
            state='drive' if abs(last_speed)>1.0 else ('charge' if last_charge>0.5 else 'idle')
            samples.append({'ts_ns':int(frame.ts_ns),'state':state,'speed':last_speed,'charge_power':last_charge})
    if not samples:return {'segments':[],'samples':0,'status':'no_supported_decoded_signals'}
    segments=[];start=samples[0]
    for current in samples[1:]:
        if current['state']!=start['state']:
            segments.append({'state':start['state'],'start_ts_ns':start['ts_ns'],'end_ts_ns':current['ts_ns'],'duration_s':round((current['ts_ns']-start['ts_ns'])/1e9,3)})
            start=current
    end=samples[-1]
    segments.append({'state':start['state'],'start_ts_ns':start['ts_ns'],'end_ts_ns':end['ts_ns'],'duration_s':round((end['ts_ns']-start['ts_ns'])/1e9,3)})
    return {'segments':segments,'samples':len(samples),'status':'decoder_based_hypothesis','note':'Segmentation depends on the currently attached decoder signal names and is not vehicle identity evidence.'}
