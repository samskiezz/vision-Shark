import argparse,json,os,platform,shutil,socket,sys
from pathlib import Path
from . import __version__

def main(argv=None):
    p=argparse.ArgumentParser(prog='vision-shark');p.add_argument('--version',action='version',version=__version__);sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('serve');s.add_argument('--data-dir',default=os.getenv('VISION_DATA_DIR','data'));s.add_argument('--host',default='127.0.0.1');s.add_argument('--port',type=int,default=8787)
    sub.add_parser('doctor');a=p.parse_args(argv)
    if a.command=='doctor':
        print(json.dumps({'app_version':__version__,'python':platform.python_version(),'python_supported':sys.version_info>=(3,11),'live_can_os_available':hasattr(socket,'AF_CAN'),'linux_ip_tool':bool(shutil.which('ip')),'note':'software prerequisites only; not vehicle validation'},indent=2));return 0
    if a.command=='serve':
        if a.host not in ('127.0.0.1','localhost','::1'):p.error('This build defaults to loopback; use the documented TLS deployment for LAN access')
        from .api import create_app
        import uvicorn
        print(f'Vision Shark {__version__} | http://{a.host}:{a.port}',flush=True);uvicorn.run(create_app(Path(a.data_dir)),host=a.host,port=a.port,server_header=False);return 0
    return 1

def cli():raise SystemExit(main())
if __name__=='__main__':cli()
