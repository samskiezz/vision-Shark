import argparse,json,os,platform,secrets,shutil,socket,sys
from pathlib import Path
from . import __version__

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
        'vehicle_validation':'not_performed',
        'server_security':'token session + role + CSRF + idempotency on vision-shark serve',
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
        admin_token=os.getenv('VISION_API_TOKEN')
        generated=not bool(admin_token)
        if generated:admin_token=secrets.token_urlsafe(32)
        viewer_token=os.getenv('VISION_VIEWER_TOKEN') or None
        from .secure_app import create_secured_app
        import uvicorn
        print(f'Vision Shark {__version__} | http://{a.host}:{a.port}',flush=True)
        if generated:print(f'Admin access token (shown once): {admin_token}',flush=True)
        else:print('Admin access token loaded from VISION_API_TOKEN.',flush=True)
        if viewer_token:print('Optional viewer role enabled from VISION_VIEWER_TOKEN.',flush=True)
        uvicorn.run(create_secured_app(Path(a.data_dir),admin_token,viewer_token),host=a.host,port=a.port,server_header=False);return 0
    return 1

def cli():raise SystemExit(main())
if __name__=='__main__':cli()
