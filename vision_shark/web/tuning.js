let tuningArtifact=null;

function parseAddress(value){
  const text=String(value||'0').trim();
  const parsed=Number(text||'0');
  if(!Number.isInteger(parsed)||parsed<0||parsed>0xffffffff)throw Error('Base address must be a 32-bit decimal or 0x-prefixed integer.');
  return parsed;
}

function bytesToBase64(bytes){
  let binary='';
  const chunk=0x8000;
  for(let i=0;i<bytes.length;i+=chunk)binary+=String.fromCharCode(...bytes.subarray(i,Math.min(i+chunk,bytes.length)));
  return btoa(binary);
}

function base64ToBytes(value){
  const binary=atob(value);const bytes=new Uint8Array(binary.length);
  for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
  return bytes;
}

async function readTuneArtifact(){
  const file=$('#tuneFile').files?.[0];
  if(!file)throw Error('Select a BIN, Intel HEX or Motorola S-record file first.');
  if(file.size>6*1024*1024)throw Error('Browser tuning workspace accepts files up to 6 MiB.');
  const bytes=new Uint8Array(await file.arrayBuffer());
  tuningArtifact={
    filename:file.name,
    format:$('#tuneFormat').value,
    data_base64:bytesToBase64(bytes),
    base_address:parseAddress($('#tuneBase').value)
  };
  return tuningArtifact;
}

async function currentTuneArtifact(){
  return tuningArtifact||readTuneArtifact();
}

function parseTuneDefinition(){
  const text=$('#tuneDefinition').value.trim();
  if(!text)throw Error('Paste a reviewed calibration definition JSON first.');
  try{return JSON.parse(text)}catch{throw Error('Calibration definition is not valid JSON.');}
}

function parseTuneEdits(){
  const text=$('#tuneEdits').value.trim();
  if(!text)throw Error('Enter calibration edits as JSON.');
  let value;
  try{value=JSON.parse(text)}catch{throw Error('Calibration edits are not valid JSON.');}
  if(!Array.isArray(value)||!value.length)throw Error('Calibration edits must be a non-empty JSON array.');
  return value;
}

function tuningRoleCheck(){
  if(securityEnabled&&authRole!=='admin')throw Error('Admin role required for tuning workspace operations.');
}

async function tuneInspect(){
  tuningRoleCheck();const artifact=await readTuneArtifact();
  const result=await api('/api/tuning/artifact/inspect',{method:'POST',body:JSON.stringify(artifact)});
  show('#tuneResult',result);return result;
}

async function tuneDecode(){
  tuningRoleCheck();const artifact=await currentTuneArtifact();const definition=parseTuneDefinition();
  const result=await api('/api/tuning/calibration/decode',{method:'POST',body:JSON.stringify({...artifact,definition})});
  show('#tuneResult',result);return result;
}

function candidateFilename(original,format){
  const stem=String(original||'calibration').replace(/\.[^.]+$/,'');
  const ext=format==='ihex'?'hex':format==='srec'?'s19':'bin';
  return `${stem}.vision.${ext}`;
}

function prepareCandidate(result,original){
  const bytes=base64ToBytes(result.candidate_base64);const blob=new Blob([bytes],{type:'application/octet-stream'});
  const link=$('#tuneSave');
  if(link.dataset.objectUrl)URL.revokeObjectURL(link.dataset.objectUrl);
  const url=URL.createObjectURL(blob);link.dataset.objectUrl=url;link.href=url;link.download=candidateFilename(original,result.output_format);link.hidden=false;
  link.textContent=`SAVE CANDIDATE · ${result.changed_bytes} BYTE${result.changed_bytes===1?'':'S'} CHANGED`;
}

async function tuneBuild(){
  tuningRoleCheck();const artifact=await currentTuneArtifact();const definition=parseTuneDefinition();const edits=parseTuneEdits();
  const result=await api('/api/tuning/calibration/build-patch',{method:'POST',body:JSON.stringify({...artifact,definition,edits,output_format:$('#tuneOutputFormat').value||null})});
  prepareCandidate(result,artifact.filename);show('#tuneResult',{...result,candidate_base64:`<${Math.ceil(result.candidate_base64.length*3/4)} encoded bytes>`});return result;
}

$('#tuneFile').addEventListener('change',()=>{tuningArtifact=null;$('#tuneSave').hidden=true;$('#tuneResult').textContent='File selected. Inspect, decode or build a candidate.';});
$('#tuneFormat').addEventListener('change',()=>{tuningArtifact=null;});
$('#tuneBase').addEventListener('change',()=>{tuningArtifact=null;});
$('#tuneInspect').onclick=()=>action(()=>tuneInspect());
$('#tuneDecode').onclick=()=>action(()=>tuneDecode());
$('#tuneBuild').onclick=()=>action(()=>tuneBuild());
