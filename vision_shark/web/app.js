const $=s=>document.querySelector(s);
async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{'content-type':'application/json',...(opts.headers||{})}});let j={};try{j=await r.json()}catch{j={detail:await r.text()}}if(!r.ok)throw Error(j.detail||j.error||r.statusText);return j}
const show=(id,value)=>{$(id).textContent=typeof value==='string'?value:JSON.stringify(value,null,2)};
function stage(id,state,detail){const e=$(id);e.className=`stage ${state}`;e.querySelector('small').textContent=detail}
function statusClass(status){return status==='ok'?'ok':status==='error'?'bad':'warn'}
async function safe(path){try{return {ok:true,value:await api(path)}}catch(error){return {ok:false,error}}}
function summarizeHealth(h){const e=$('#healthSummary');e.textContent=(h.status||'unknown').toUpperCase();e.className=`big-status ${statusClass(h.status)}`;$('#healthChecks').innerHTML=(h.checks||[]).map(x=>`<div class="check ${statusClass(x.status)}"><span>${x.name.replaceAll('_',' ')}</span><b>${x.status.toUpperCase()}</b></div>`).join('')||'No health data.'}
function summarizeOpenClaw(caps,intents){const e=$('#openclawSummary');if(!caps){e.textContent='OFFLINE';e.className='big-status bad';return}e.textContent=caps.direct_driving?'POLICY ERROR':'READY / BOUNDED';e.className=`big-status ${caps.direct_driving?'bad':'ok'}`;const pending=(intents&&intents.intents)||[];$('#intentSummary').textContent=pending.length?`${pending.length} provider intent${pending.length===1?'':'s'} pending — queued, not claimed as executed.`:'No pending provider intents.'}
async function refresh(){
  const [rr,vv,ff,re,hh,aa,cc,ii]=await Promise.all([safe('/api/production/readiness'),safe('/api/vision/status'),safe('/api/frames'),safe('/api/recordings'),safe('/api/system/health'),safe('/api/adapters'),safe('/api/openclaw/capabilities'),safe('/api/intents?state=pending')]);
  if(!vv.ok){$('#connection').textContent='GATEWAY OFFLINE';$('#connection').className='badge bad';show('#visionStatus',vv.error.message);return}
  const v=vv.value,h=hh.ok?hh.value:null,adapters=aa.ok?aa.value.adapters:[];const proof=v.diagnostic_proof||{};const source=v.source||v.runtime?.source_kind;
  const ready=Boolean(h?.vehicle_ready);$('#connection').textContent=ready?'VEHICLE READY':source==='simulator'?'SIMULATION':v.state==='error'?'CONNECTION FAILED':source?'CONNECTED / VERIFYING':'DISCONNECTED';$('#connection').className=`badge ${ready?'ok':v.state==='error'?'bad':source?'warn':''}`;
  const usable=adapters.filter(x=>x.usable!==false);stage('#adapterStage',usable.length?'ok':source==='simulator'?'warn':'idle',source==='simulator'?'simulation':usable.length?`${usable[0].transport} · ${usable[0].interface}`:'not detected');
  const vehicleSeen=Boolean(v.vehicle);stage('#vehicleStage',vehicleSeen?'ok':source==='simulator'?'warn':'idle',vehicleSeen?(v.vehicle.vin||v.vehicle.status||'observed'):source==='simulator'?'simulation':'not observed');
  if(source==='doip')stage('#diagStage',proof.uds_exchange?'ok':v.state==='error'?'bad':'warn',proof.uds_exchange?'routed UDS proven':proof.error||'not proven');
  else if(source==='socketcan')stage('#diagStage',(v.runtime?.frames_seen||0)>0?'ok':'warn',(v.runtime?.frames_seen||0)>0?`${v.runtime.frames_seen} frames observed`:'waiting for traffic');
  else stage('#diagStage',source==='simulator'?'warn':'idle',source==='simulator'?'simulation only':'waiting');
  stage('#readyStage',ready?'ok':v.state==='error'?'bad':'idle',ready?'physical comms proven':v.state==='error'?'failed':'not proven');
  if(rr.ok)show('#readiness',rr.value);show('#visionStatus',v);show('#adapters',aa.ok?aa.value:aa.error.message);show('#recordings',re.ok?re.value.recordings.slice(0,10):re.error.message);
  const signals=v.runtime?.signals||{};show('#signals',Object.keys(signals).length?signals:'No current decoded signals.');
  const frames=ff.ok?ff.value.frames:[];$('#frames').innerHTML=frames.length?frames.slice(-20).reverse().map(x=>`<code>${x.bus} 0x${Number(x.arbitration_id).toString(16)} ${x.data}</code>`).join(''):'No frames observed.';
  const active=v.runtime?.recording_id;$('#recordingSummary').textContent=active?`Recording #${active} active · ${v.runtime.frames_seen||0} frames seen`:`Not recording · ${(re.ok?re.value.recordings.length:0)} saved session(s)`;
  if(h)summarizeHealth(h);summarizeOpenClaw(cc.ok?cc.value:null,ii.ok?ii.value:null);
  $('#readVin').disabled=!(source==='doip'&&proof.uds_exchange);$('#readDtcs').disabled=$('#readVin').disabled;
}
async function action(fn){try{const result=await fn();if(result)show('#toolResult',result);await refresh()}catch(e){show('#toolResult',e.message);await refresh()}}
$('#autoConnect').onclick=()=>action(()=>api('/api/vision/connect',{method:'POST',body:JSON.stringify({simulation:false})}));
$('#demo').onclick=()=>action(()=>api('/api/vision/connect',{method:'POST',body:JSON.stringify({simulation:true})}));
$('#identify').onclick=()=>action(()=>api('/api/vision/identify',{method:'POST',body:JSON.stringify({settle_s:.5})}));
$('#learn').onclick=()=>action(()=>api('/api/vision/learn',{method:'POST'}));
$('#readVin').onclick=()=>action(()=>api('/api/diagnostics/doip/dids',{method:'POST',body:JSON.stringify({dids:[0xF190]})}));
$('#readDtcs').onclick=()=>action(()=>api('/api/diagnostics/doip/dtcs',{method:'POST',body:JSON.stringify({status_mask:255})}));
$('#disconnect').onclick=()=>action(()=>api('/api/disconnect',{method:'POST'}));
$('#record').onclick=()=>action(()=>api('/api/recordings/start',{method:'POST',body:JSON.stringify({metadata:{operator:'ui'}})}));
$('#stopRecord').onclick=()=>action(()=>api('/api/recordings/stop',{method:'POST'}));
refresh();setInterval(refresh,1500);
