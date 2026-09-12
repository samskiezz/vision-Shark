const $=s=>document.querySelector(s);
async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{'content-type':'application/json',...(opts.headers||{})}});const j=await r.json();if(!r.ok)throw Error(j.detail||j.error||r.statusText);return j}
function show(id,value){$(id).textContent=typeof value==='string'?value:JSON.stringify(value,null,2)}
async function refresh(){try{const [r,v,f,recs]=await Promise.all([api('/api/production/readiness'),api('/api/vision/status'),api('/api/frames'),api('/api/recordings')]);show('#readiness',r);show('#visionStatus',v);$('#connection').textContent=v.runtime.connected?(v.runtime.simulated?'SIMULATION':'CONNECTED'):'DISCONNECTED';show('#signals',Object.keys(v.runtime.signals||{}).length?v.runtime.signals:'No current decoded signals.');$('#frames').innerHTML=f.frames.slice(-20).reverse().map(x=>`<code>${x.bus} 0x${Number(x.arbitration_id).toString(16)} ${x.data}</code>`).join('');show('#recordings',recs.recordings.slice(0,10))}catch(e){$('#connection').textContent='GATEWAY OFFLINE';show('#visionStatus',e.message)}}
async function action(fn){try{await fn();await refresh()}catch(e){show('#visionStatus',e.message)}}
$('#autoConnect').onclick=()=>action(()=>api('/api/vision/connect',{method:'POST',body:JSON.stringify({simulation:false})}));
$('#demo').onclick=()=>action(()=>api('/api/vision/connect',{method:'POST',body:JSON.stringify({simulation:true})}));
$('#identify').onclick=()=>action(()=>api('/api/vision/identify',{method:'POST',body:JSON.stringify({settle_s:.5})}));
$('#learn').onclick=()=>action(()=>api('/api/vision/learn',{method:'POST'}));
$('#disconnect').onclick=()=>action(()=>api('/api/disconnect',{method:'POST'}));
$('#record').onclick=()=>action(()=>api('/api/recordings/start',{method:'POST',body:JSON.stringify({metadata:{operator:'ui'}})}));
$('#stopRecord').onclick=()=>action(()=>api('/api/recordings/stop',{method:'POST'}));
refresh();setInterval(refresh,1000);
