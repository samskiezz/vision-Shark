import argparse,json,os,platform,secrets,shutil,socket,sys
from pathlib import Path
from . import __version__

def _truthy(name):return os.getenv(name,'').strip().lower() in {'1','true','yes','on'}

def _security_report():
    disabled=_truthy('VISION_SECURITY_DISABLED')
    configured=[role for role,name in (('viewer','VISION_VIEWER_TOKEN'),('operator','VISION_OPERATOR_TOKEN'),('admin','VISION_ADMIN_TOKEN')) if os.getenv(name)]
    return {'enabled':not disabled,'configured_roles':configured,'ephemeral_admin_will_be_generated':not disabled and not configured}

def _ensure_server_security():
    if _truthy('VISION_SECURITY_DISABLED'):return None
    if any(os.getenv(name) for name in ('VISION_VIEWER_TOKEN','VISION_OPERATOR_TOKEN','VISION_ADMIN_TOKEN')):return None
    token=secrets.token_urlsafe(32);os.environ['VISION_ADMIN_TOKEN']=token;return token

def _doctor_report():
    from .adapter_discovery import network_interfaces,discover_j2534_registry
    interfaces=network_interfaces();j2534=discover_j2534_registry()
    return {
        'app_version':__version__,
        'python':platform.python_version(),
        'python_supported':sys.version_info>=(3,11),
        'os':platform.platform(),
        'network_interfaces':interfaces,
        'ethernet_ipv4_ready':any(x.get('ipv4') for x in interfaces),
        'socketcan_os_available':hasattr(socket,'AF_CAN'),
        'linux_ip_tool':bool(shutil.which('ip')),
        'j2534_providers':[{'interface':x.interface,'endpoint':x.endpoint,'metadata':x.metadata} for x in j2534],
        'http_security':_security_report(),
        'vehicle_validation':'not_performed',
        'next_step':'connect the OBD adapter and vehicle, then run vision-shark probe --prove-diagnostics',
    }

def main(argv=None):
    p=argparse.ArgumentParser(prog='vision-shark');p.add_argument('--version',action='version',version=__version__);sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('serve');s.add_argument('--data-dir',default=os.getenv('VISION_DATA_DIR','data'));s.add_argument('--host',default='127.0.0.1');s.add_argument('--port',type=int,default=8787)
    sub.add_parser('doctor')
    probe=sub.add_parser('probe');probe.add_argument('--prove-diagnostics',action='store_true');probe.add_argument('--timeout',type=float,default=.75)
    a=p.parse_args(argv)
    if a.command=='doctor':
        print(json.dumps(_doctor_report(),indent=2));return 0
    if a.command=='probe':
        from .adapter_discovery import discover_adapters,discover_doip
        if a.timeout<=0 or a.timeout>10:p.error('--timeout must be >0 and <=10 seconds')
        found=discover_adapters(include_doip=False,include_j2534=True);found.extend(x.as_dict() for x in discover_doip(a.timeout));found.sort(key=lambda x:(bool(x.get('usable')),x.get('confidence',0)),reverse=True)
        report={'adapters':found,'usable':sum(1 for x in found if x.get('usable',True)),'diagnostic_proofs':[]}
        if a.prove_diagnostics:
            from .doip_transport import DoIPError,DoIPReadOnlyClient
            for item in found:
                if item.get('transport')!='doip' or not item.get('usable',True):continue
                try:proof=DoIPReadOnlyClient(item['endpoint'],item['logical_address']).prove_readonly_session();report['diagnostic_proofs'].append({'endpoint':item['endpoint'],'logical_address':item['logical_address'],'ok':True,'proof':proof})
                except (DoIPError,OSError,TimeoutError,ValueError) as exc:report['diagnostic_proofs'].append({'endpoint':item.get('endpoint'),'logical_address':item.get('logical_address'),'ok':False,'error':f'{type(exc).__name__}: {exc}'})
        print(json.dumps(report,indent=2))
        if a.prove_diagnostics:return 0 if any(x.get('ok') for x in report['diagnostic_proofs']) else 2
        return 0 if report['usable'] else 2
    if a.command=='serve':
        if a.host not in ('127.0.0.1','localhost','::1'):p.error('This build is loopback-only; use a separately authenticated/TLS deployment for LAN access')
        generated=_ensure_server_security()
        from .api import create_app
        import uvicorn
        print(f'Vision Shark {__version__} | http://{a.host}:{a.port}',flush=True)
        if _truthy('VISION_SECURITY_DISABLED'):print('WARNING: HTTP security explicitly disabled by VISION_SECURITY_DISABLED=1',flush=True)
        elif generated:print(f'Local admin token (enter in the Vision Shark UI): {generated}',flush=True)
        else:print('HTTP security enabled using configured role token(s).',flush=True)
        uvicorn.run(create_app(Path(a.data_dir)),host=a.host,port=a.port,server_header=False);return 0
    return 1

def cli():raise SystemExit(main())
if __name__=='__main__':cli()
