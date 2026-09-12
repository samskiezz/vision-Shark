const $=s=>document.querySelector(s);
const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const roleLevel={viewer:1,operator:2,admin:3};
let authState={security_enabled:true,authenticated:false,role:null};
let csrfToken=null;
const mutation=m=>!['GET','HEAD','OPTIONS'].includes(m);
const requestId=()=>globalThis.crypto?.randomUUID?.()||`vision-${Date.now()}-${Math.random().toString(16).slice(2)}`;
function applyAuth(state){
  authState=state||{security_enabled:true,authenticated:false,role:null};csrfToken=authState.csrf_token||null;
  const enabled=authState.security_enabled!==false,authenticated=Boolean(authState.authenticated),role=authState.role||null,level=roleLevel[role]||0;
  $('#security').textContent=!enabled?'SECURITY DISABLED':authenticated?`${String(role).toUpperCase()} SESSION`:'ACCESS LOCKED';$('#security').className=`badge ${!enabled?'warn':authenticated?'ok':'bad'}`;
  $('#authRole').textContent=!enabled?'DISABLED':authenticated?String(role).toUpperCase():'SIGNED OUT';$('#authRole').className=`badge ${!enabled?'warn':authenticated?'ok':'bad'}`;
  $('#authLoginControls').classList.toggle('hidden',!enabled||authenticated);$('#authLogout').classList.toggle('hidden',!enabled||!authenticated);
  $('#authResult').textContent=!enabled?'HTTP security is explicitly disabled for this process.':authenticated?`Authenticated as ${role}. Cookie session is HttpOnly/SameSite=Strict; browser mutations use CSRF and idempotency keys.`:'API access is locked. Enter a configured token or the local admin token printed by vision-shark serve.';
  const operator=level>=2||!enabled,admin=level>=3||!enabled;
  for(const id of ['autoConnect','demo','disconnect','identify','learn','readVin','readDtcs','record','stopRecord'])$("#"+id).disabled=!operator;
  $('#enetConnect').disabled=!admin;
}
async function api(path,opts={}){
  const method=String(opts.method||'GET').toUpperCase();const headers={...(opts.headers||{})};
  if(opts.body!==undefined&&!Object.keys(headers).some(k=>k.toLowerCase()==='content-type'))headers['content-type']='application/json';
  if(mutation(method)&&path!='/api/auth/session'){
    if(csrfToken&&!Object.keys(headers).some(k=>k.toLowerCase()==='x-csrf-token'))headers['X-CSRF-Token']=csrfToken;
    if(!Object.keys(headers).some(k=>k.toLowerCase()==='idempotency-key'))headers['Idempotency-Key']=requestId();
  }
  const r=await fetch(path,{...opts,method,headers});let j={};try{j=await r.json()}catch{j={detail:await r.text()}}
  if(r.status===401&&path!='/api/auth/session'&&path!='/api/auth/status')applyAuth({security_enabled:true,authenticated:false,role:null,csrf_token:null});
  if(!r.ok)throw Error(j.detail||j.error||r.statusText);return j
}
const show=(id,value)=>{$(id).textContent=typeof value==='string'?value:JSON.stringify(value,null,2)};
function stage(id,state,detail){const e=$(id);e.className=`stage ${state}`;e.querySelector('small').textContent=detail}
function statusClass(status){return status==='ok'?'ok':status==='error'?'bad':'warn'}
async function safe(path){try{return {ok:true,value:await api(path)}}catch(error){return {ok:false,error}}}
function summarizeHealth(h){const e=$('#healthSummary');e.textContent=(h.status||'unknown').toUpperCase();e.className=`big-status ${statusClass(h.status)}`;$('#healthChecks').innerHTML=(h.checks||[]).map(x=>`<div class="check ${statusClass(x.status)}"><span>${esc(String(x.name||'').replaceAll('_',' '))}</span><b>${esc(String(x.status||'unknown').toUpperCase())}</b></div>`).join('')||'No health data.'}
function summarizeOpenClaw(caps,intents){const e=$('#openclawSummary');if(!caps){e.textContent='OFFLINE';e.className='big-status bad';return}e.textContent=caps.direct_driving?'POLICY ERROR':'READY / BOUNDED';e.className=`big-status ${caps.direct_driving?'bad':'ok'}`;const pending=(intents&&intents.intents)||[];$('#intentSummary').textContent=pending.length?`${pending.length} provider intent${pending.length===1?'':'s'} pending — queued, not claimed as executed.`:'No pending provider intents.'}
function renderSniffer(report){const rows=report?.messages||[];$('#snifferSummary').textContent=rows.length?`${rows.length} message IDs · ${report.frame_count||0} observed frames · byte highlight window ${report.changed_within_ms||1500} ms`:'Waiting for receive traffic.';$('#sniffer').innerHTML=rows.length?rows.slice(0,80).map(row=>{const bytes=(row.bytes||[]).map(byte=>`<span class="sniff-byte ${byte.changed_recently?'changed':''}" title="byte ${byte.index} · ${byte.change_count} changes · age ${byte.last_change_age_ms??'n/a'} ms">${esc(byte.value??'--')}</span>`).join('');return `<div class="sniff-row"><code>${esc(row.bus)} ${esc(row.id_hex)}</code><div class="sniff-bytes">${bytes}</div><small>${Number(row.count||0)} frames</small></div>`}).join(''):'No CAN/CAN-FD messages observed.'}
function applyRoleControls(source,proof){const enabled=authState.security_enabled!==false,level=enabled?(roleLevel[authState.role]||0):3,operator=level>=2,admin=level>=3;for(const id of ['autoConnect','demo','disconnect','identify','learn','record','stopRecord'])$("#"+id).disabled=!operator;$('#enetConnect').disabled=!admin;$('#readVin').disabled=!(operator&&source==='doip'&&proof?.uds_exchange);$('#readDtcs').disabled=$('#readVin').disabled}
async function refresh(){
  if(!authState.authenticated)return;
  const changedOnly=$('#changedOnly')?.checked?'true':'false';
  const [rr,vv,ff,re,hh,aa,cc,ii,ss]=await Promise.all([safe('/api/production/readiness'),safe('/api/vision/status'),safe('/api/frames'),safe('/api/recordings'),safe('/api/system/health'),safe('/api/adapters'),safe('/api/openclaw/capabilities'),safe('/api/intents?state=pending'),safe(`/api/sniffer?changed_only=${changedOnly}&changed_within_ms=1500`)]);
  if(!vv.ok){$('#connection').textContent=vv.error.message.includes('Authentication')?'ACCESS LOCKED':'GATEWAY OFFLINE';$('#connection').className='badge bad';show('#visionStatus',vv.error.message);return}
  const v=vv.value,h=hh.ok?hh.value:null,adapters=aa.ok?aa.value.adapters:[];const proof=v.diagnostic_proof||{};const source=v.source||v.runtime?.source_kind;
  const ready=Boolean(h?.vehicle_ready);$('#connection').textContent=ready?'VEHICLE READY':source==='simulator'?'SIMULATION':v.state==='error'?'CONNECTION FAILED':source?'CONNECTED / VERIFYING':'DISCONNECTED';$('#connection').className=`badge ${ready?'ok':v.state==='error'?'bad':source?'warn':''}`;
  const usable=adapters.filter(x=>x.usable!==false);if(source==='doip')stage('#adapterStage','ok',`doip · ${v.interface||'ethernet'}`);else stage('#adapterStage',usable.length?'ok':source==='simulator'?'warn':'idle',source==='simulator'?'simulation':usable.length?`${usable[0].transport} · ${usable[0].interface}`:'not detected');
  const vehicle=v.vehicle||{};const vehicleSeen=Object.keys(vehicle).length>0;stage('#vehicleStage',vehicleSeen?'ok':source==='simulator'?'warn':'idle',vehicleSeen?(vehicle.vin||vehicle.status||'observed'):source==='simulator'?'simulation':'not observed');
  if(source==='doip')stage('#diagStage',proof.uds_exchange?'ok':v.state==='error'?'bad':'warn',proof.uds_exchange?'routed UDS proven':proof.error||'not proven');
  else if(source==='socketcan')stage('#diagStage',(v.runtime?.frames_seen||0)>0?'ok':'warn',(v.runtime?.frames_seen||0)>0?`${v.runtime.frames_seen} frames observed`:'waiting for traffic');
  else stage('#diagStage',source==='simulator'?'warn':'idle',source==='simulator'?'simulation only':'waiting');
  stage('#readyStage',ready?'ok':v.state==='error'?'bad':'idle',ready?'physical comms proven':v.state==='error'?'failed':'not proven');
  if(rr.ok)show('#readiness',rr.value);show('#visionStatus',v);show('#adapters',aa.ok?aa.value:aa.error.message);show('#recordings',re.ok?re.value.recordings.slice(0,10):re.error.message);
  const signals=v.runtime?.signals||{};show('#signals',Object.keys(signals).length?signals:'No current decoded signals.');
  const frames=ff.ok?ff.value.frames:[];$('#frames').innerHTML=frames.length?frames.slice(-20).reverse().map(x=>`<code>${esc(x.bus)} 0x${Number(x.arbitration_id).toString(16)} ${esc(x.data)}</code>`).join(''):'No frames observed.';
  const active=v.runtime?.recording_id;$('#recordingSummary').textContent=active?`Recording #${active} active · ${v.runtime.frames_seen||0} frames seen`:`Not recording · ${(re.ok?re.value.recordings.length:0)} saved session(s)`;
  if(h)summarizeHealth(h);summarizeOpenClaw(cc.ok?cc.value:null,ii.ok?ii.value:null);renderSniffer(ss.ok?ss.value:null);applyRoleControls(source,proof)
}
async function refreshAuth(){try{const state=await api('/api/auth/status');applyAuth(state);if(state.authenticated)await refresh()}catch(error){applyAuth({security_enabled:true,authenticated:false,role:null});$('#authResult').textContent=error.message}}
async function action(fn){try{const result=await fn();if(result)show('#toolResult',result);await refresh()}catch(e){show('#toolResult',e.message);if(authState.authenticated)await refresh()}}
$('#authLogin').onclick=async()=>{const token=$('#authToken').value;try{const state=await api('/api/auth/session',{method:'POST',body:JSON.stringify({token})});$('#authToken').value='';applyAuth(state);await refresh()}catch(error){$('#authResult').textContent=error.message}};
$('#authToken').addEventListener('keydown',event=>{if(event.key==='Enter')$('#authLogin').click()});
$('#authLogout').onclick=async()=>{try{await api('/api/auth/logout',{method:'POST'});csrfToken=null;await refreshAuth()}catch(error){$('#authResult').textContent=error.message}};
$('#autoConnect').onclick=()=>action(()=>api('/api/vision/connect',{method:'POST',body:JSON.stringify({simulation:false})}));
$('#enetConnect').onclick=()=>action(async()=>{const discovery=await api('/api/discovery/adapters',{method:'POST',body:JSON.stringify({include_doip:true,include_j2534:false})});const doip=(discovery.adapters||[]).find(x=>x.transport==='doip'&&x.usable!==false);if(!doip)throw Error('No DoIP vehicle responded to the explicit discovery request.');return api('/api/vision/connect-doip',{method:'POST',body:JSON.stringify({endpoint:doip.endpoint,logical_address:doip.logical_address,interface:doip.interface||'ethernet',discovery_vin:doip.vin||null,eid:doip.eid||null,metadata:doip.metadata||{}})})});
$('#demo').onclick=()=>action(()=>api('/api/vision/connect',{method:'POST',body:JSON.stringify({simulation:true})}));
$('#identify').onclick=()=>action(()=>api('/api/vision/identify',{method:'POST',body:JSON.stringify({settle_s:.5})}));
$('#learn').onclick=()=>action(()=>api('/api/vision/learn',{method:'POST'}));
$('#readVin').onclick=()=>action(()=>api('/api/diagnostics/doip/dids',{method:'POST',body:JSON.stringify({dids:[0xF190]})}));
$('#readDtcs').onclick=()=>action(()=>api('/api/diagnostics/doip/dtcs',{method:'POST',body:JSON.stringify({status_mask:255})}));
$('#disconnect').onclick=()=>action(()=>api('/api/disconnect',{method:'POST'}));
$('#record').onclick=()=>action(()=>api('/api/recordings/start',{method:'POST',body:JSON.stringify({metadata:{operator:'ui'}})}));
$('#stopRecord').onclick=()=>action(()=>api('/api/recordings/stop',{method:'POST'}));
$('#changedOnly').onchange=()=>refresh();
applyAuth({security_enabled:true,authenticated:false,role:null});refreshAuth();setInterval(()=>{if(authState.authenticated)refresh()},1500);
