class FallbackManager:
 def decide(self,*,odd_inside,autonomy_healthy,driver_state=None,vehicle_fault=False):
  d=driver_state or {'available':True,'attentive':True};reasons=[]
  if vehicle_fault:reasons.append('vehicle_fault')
  if not odd_inside:reasons.append('odd_exit')
  if not autonomy_healthy:reasons.append('autonomy_health')
  if not d.get('available',True):reasons.append('driver_unavailable')
  if not reasons:return {'state':'normal','reasons':[]}
  if vehicle_fault or not d.get('available',True):return {'state':'minimum_risk','reasons':reasons}
  if not d.get('attentive',True):return {'state':'takeover_request','reasons':reasons+['driver_attention']}
  return {'state':'degraded','reasons':reasons}
