"""Isolated Linux production rehearsal: venv, Nginx, tests, proxy, restart persistence."""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

root=Path(__file__).resolve().parents[1]
out=root/'artifacts/deployment';out.mkdir(parents=True,exist_ok=True)
result={'environment':Path('/etc/os-release').read_text(),'publicDeployment':False,'checks':[]}
def free_port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
with tempfile.TemporaryDirectory(prefix='vps-linux-') as temp:
    work=Path(temp);env={**os.environ,'VPS_DATA_DIR':str(work/'runtime'),'OPENBLAS_NUM_THREADS':'2','OMP_NUM_THREADS':'2'}
    for proxy in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:env.pop(proxy,None)
    logs=(out/'linux-rehearsal.log').open('w',encoding='utf-8')
    backend=nginx=None
    def run(args,**kw):
        subprocess.run(args,env=env,stdout=logs,stderr=subprocess.STDOUT,check=True,**kw)
    try:
        run([sys.executable,'-m','venv',str(work/'venv')])
        python=str(work/'venv/bin/python')
        run([python,'-m','pip','install','-r',str(root/'backend/requirements.txt')])
        versions=subprocess.check_output([python,'-c','import json,importlib.metadata as m;print(json.dumps({p:m.version(p) for p in ["fastapi","uvicorn","pandas","numpy","scipy","openpyxl","xlrd"]}))'],env=env,text=True)
        result['versions']=json.loads(versions)
        result['checks'].append('Fresh Linux venv: all requirements installed')
        run([python,'-m','pytest','tests','-q'],cwd=root/'backend')
        result['checks'].append('All 149 backend tests on Linux')
        run(['apt-get','download','nginx','nginx-common'],cwd=work)
        bundle=work/'nginx';bundle.mkdir()
        for package in work.glob('*.deb'):run(['dpkg-deb','-x',str(package),str(bundle)])
        executable=str(bundle/'usr/sbin/nginx')
        api_port,port=free_port(),free_port()
        site=(root/'deploy/nginx.conf').read_text().replace('listen 80;',f'listen 127.0.0.1:{port};').replace('/var/www/visual-pandas-studio/frontend/dist',str(root/'frontend/dist')).replace('127.0.0.1:8000',f'127.0.0.1:{api_port}')
        site=site.replace('root '+str(root/'frontend/dist')+';', 'root "'+str(root/'frontend/dist')+'";')
        config=work/'nginx.conf'
        config.write_text(f'daemon off;\npid {work}/nginx.pid;\nerror_log {work}/nginx-error.log;\nevents {{worker_connections 1024;}}\nhttp {{\ninclude {bundle}/etc/nginx/mime.types;\naccess_log {work}/nginx-access.log;\n'+''.join(f'{name}_temp_path {work}/{name};\n' for name in ['client_body','proxy','fastcgi','uwsgi','scgi'])+site+'\n}\n')
        run([executable,'-p',str(work)+'/', '-c',str(config),'-t'])
        result['checks'].append('Nginx validates the delivered configuration')
        def start_backend():return subprocess.Popen([python,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(api_port),'--workers','1'],cwd=root/'backend',env=env,stdout=logs,stderr=subprocess.STDOUT)
        backend=start_backend();nginx=subprocess.Popen([executable,'-p',str(work)+'/', '-c',str(config)],env=env,stdout=logs,stderr=subprocess.STDOUT)
        unit=(root/'deploy/visual-pandas-studio.service').read_text().replace('WorkingDirectory=/var/www/visual-pandas-studio/backend','WorkingDirectory='+str(root/'backend')).replace('EnvironmentFile=/etc/visual-pandas-studio.env','EnvironmentFile='+str(work/'app.env')).replace('/var/www/visual-pandas-studio/backend/.venv/bin/python',python).replace('/var/lib/visual-pandas-studio',str(work/'runtime'))
        (work/'app.env').write_text('VPS_DATA_DIR='+str(work/'runtime')+'\n')
        (work/'studio.service').write_text(unit)
        run(['systemd-analyze','verify',str(work/'studio.service')])
        result['checks'].append('systemd unit validation with real executable and environment paths')
        # Wait using the venv's HTTP client; keep the host runner dependency-free.
        wait='import httpx,time\nfor _ in range(100):\n try:\n  if httpx.get("http://127.0.0.1:'+str(port)+'/api/health",trust_env=False).status_code==200: break\n except httpx.TransportError: pass\n time.sleep(.1)\nelse: raise RuntimeError("service not ready")'
        run([python,'-c',wait])
        run([python,str(root/'deploy/verify_http.py'),f'http://127.0.0.1:{port}','--output',str(out/'nginx-http-verification.json')])
        result['checks'].append('Actual Nginx + Linux FastAPI: all production HTTP checks passed')
        # A new private fixture survives an actual service process restart.
        state=work/'restart-state.json'
        code='import httpx,uuid,json\nc=httpx.Client(base_url="http://127.0.0.1:'+str(api_port)+'",headers={"X-Studio-Session":str(uuid.uuid4())},trust_env=False)\nd=c.post("/api/samples/iris").json()\nopen('+repr(str(state))+',"w").write(json.dumps({"id":d["id"],"token":c.headers["X-Studio-Session"]}))'
        run([python,'-c',code])
        backend.terminate();backend.wait(timeout=15);backend=start_backend();run([python,'-c',wait])
        code='import httpx,json\ns=json.load(open('+repr(str(state))+'))\nc=httpx.Client(base_url="http://127.0.0.1:'+str(api_port)+'",headers={"X-Studio-Session":s["token"]},trust_env=False)\nr=c.get("/api/datasets/"+s["id"])\nassert r.status_code==200 and r.json()["overview"]["rows"]==150\nassert c.delete("/api/datasets/"+s["id"]).status_code==200'
        run([python,'-c',code]);result['checks'].append('SQLite data survives actual backend restart')
        result['passed']=True
    except Exception as exc:
        result.update(passed=False,error=repr(exc));raise
    finally:
        for process in [nginx,backend]:
            if process and process.poll() is None:process.terminate();process.wait(timeout=15)
        if (work/'nginx-error.log').exists():(out/'nginx-error.log').write_bytes((work/'nginx-error.log').read_bytes())
        logs.close();(out/'linux-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2),flush=True)
