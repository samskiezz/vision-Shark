function runCardPayload(){
  const vehicleId=$('#runVehicleId').value.trim();
  if(!vehicleId)throw Error('Vehicle ID is required for a research run.');
  const trailerMassRaw=$('#runTrailerMass').value.trim();
  const ambientRaw=$('#runAmbient').value.trim();
  const mods=$('#runMods').value.split(',').map(x=>x.trim()).filter(Boolean);
  const trailerMass=trailerMassRaw===''?null:Number(trailerMassRaw);
  const ambient=ambientRaw===''?null:Number(ambientRaw);
  if(trailerMass!==null&&!Number.isFinite(trailerMass))throw Error('Trailer mass must be a number.');
  if(ambient!==null&&!Number.isFinite(ambient))throw Error('Ambient temperature must be a number.');
  return {
    vehicle_id:vehicleId,
    model:'BYD Shark 6',
    variant:$('#runVariant').value.trim()||'unknown',
    firmware:$('#runFirmware').value.trim()||'unknown',
    purpose:$('#runPurpose').value.trim()||'general',
    terrain:$('#runTerrain').value.trim()||'unknown',
    tyres:$('#runTyres').value.trim()||'unknown',
    ambient_c:ambient,
    modification_ids:mods,
    trailer:{
      physically_attached:trailerMass!==null?true:null,
      detected_by_vehicle:null,
      tow_mode_observed:null,
      estimated_mass_kg:trailerMass,
      notes:''
    },
    operator_notes:$('#runNotes').value.trim(),
    provenance:[{source:'operator-run-card',confidence:'operator-entered'}]
  };
}

async function startResearchRun(){
  if(securityEnabled&&authRole!=='admin'){
    show('#toolResult','Admin role required for state-changing actions.');
    return;
  }
  let started=null;
  try{
    const context=runCardPayload();
    started=await api('/api/recordings/start',{method:'POST',body:JSON.stringify({metadata:{operator:'ui',research_run:true}})});
    const stored=await api(`/api/research/session-context/${started.recording_id}`,{method:'POST',body:JSON.stringify(context)});
    $('#recordingSummary').textContent=`Recording #${started.recording_id} active · run card ${stored.sha256.slice(0,12)}…`;
    show('#toolResult',{recording_id:started.recording_id,session_context:stored.context,context_sha256:stored.sha256});
    await refresh();
  }catch(error){
    if(started?.recording_id){
      try{await api('/api/recordings/stop',{method:'POST'});}catch{}
    }
    show('#toolResult',error.message);
    await refresh();
  }
}

async function refreshResearchSummary(){
  if(securityEnabled&&!authenticated)return;
  const result=await safe('/api/research/summary');
  if(result.ok){
    const r=result.value;
    $('#researchSummary').textContent=`${r.sources} sources · ${r.claims} claims · ${r.incidents} incidents · ${r.test_protocols} protocols`;
  }else if(result.error?.status!==401){
    $('#researchSummary').textContent='Research store unavailable.';
  }
}

$('#record').textContent='START RESEARCH RUN';
$('#record').onclick=()=>startResearchRun();
setInterval(refreshResearchSummary,3000);
refreshResearchSummary();
