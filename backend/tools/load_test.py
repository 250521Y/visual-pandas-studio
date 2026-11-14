"""Reproducible isolated HTTP capacity test. Never touches the normal data directory."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time
import uuid
import httpx
import numpy as np
import pandas as pd
import psutil

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=100000)
    parser.add_argument('--users', type=int, default=8)
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--wide', action='store_true')
    parser.add_argument('--rounds', type=int, default=12)
    args = parser.parse_args()
    assert 1000 <= args.rows <= 100000 and 1 <= args.users <= 16 and 1 <= args.rounds <= 100
    root = Path(__file__).resolve().parents[2]
    out = root / 'artifacts' / 'capacity'
    run = out / time.strftime('%Y%m%d-%H%M%S')
    run.mkdir(parents=True)
    env = {**os.environ, 'VPS_DATA_DIR': str(run / 'runtime'), 'OPENBLAS_NUM_THREADS': '2', 'OMP_NUM_THREADS': '2'}
    log = (run / 'server.log').open('w', encoding='utf-8')
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(args.port), '--workers', '1'], cwd=root / 'backend', env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f'http://127.0.0.1:{args.port}'
    samples, memory, failures = [], [], []
    stop = threading.Event()
    def monitor():
        worker = psutil.Process(process.pid)
        while not stop.wait(.1):
            try:
                rss = worker.memory_info().rss
                memory.append(rss)
                if rss > 1900 * 1024**2:
                    failures.append('Owned test server exceeded 1,900 MiB memory guard')
                    process.terminate()
                    return
            except psutil.NoSuchProcess:
                return
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    def client():
        return httpx.Client(base_url=url, headers={'X-Studio-Session': str(uuid.uuid4())}, trust_env=False, timeout=120)
    def request(c, method, path, label, expected=200, **kwargs):
        start = time.perf_counter()
        response = c.request(method, path, **kwargs)
        samples.append({'label': label, 'seconds': round(time.perf_counter()-start, 4), 'status': response.status_code, 'bytes': len(response.content)})
        assert response.status_code == expected, (label, response.status_code, response.text[:500])
        return response
    def upload(c, raw, label):
        return request(c, 'POST', '/api/upload', label, files={'file': ('capacity.csv', raw, 'text/csv')}).json()
    n = args.rows
    frame = pd.DataFrame({'id': np.arange(n), 'team': np.array(['A','B','C','D'])[np.arange(n)%4], 'time': pd.date_range('2024-01-01', periods=n, freq='min')})
    for i in range(9): frame[f'v{i}'] = (np.arange(n) % (100+i)).astype(float)
    raw = frame.to_csv(index=False).encode()
    result = {'environment': {'python': platform.python_version(), 'platform': platform.platform(), 'cpu': platform.processor(), 'logicalCPUs': os.cpu_count(), 'RAMGiB': round(psutil.virtual_memory().total/1024**3,2)}, 'config': vars(args), 'csvBytes': len(raw)}
    try:
        with client() as c:
            for _ in range(100):
                try:
                    if c.get('/api/health').status_code == 200: break
                except httpx.TransportError: pass
                if process.poll() is not None: raise RuntimeError('Test server startup failed')
                time.sleep(.1)
            d = upload(c, raw, 'upload-100k')
            assert d['overview']['rows'] == n and d['overview']['columns'] == 12
            ident = d['id']
            assert request(c,'GET',f'/api/datasets/{ident}/table?offset={n-25}&limit=25','page-last').json()['ids'] == list(range(n-25,n))
            described = request(c,'POST',f'/api/datasets/{ident}/analysis','describe',json={'kind':'describe','revision':0}).json()['rows']
            assert next(r for r in described if r['field']=='v0')['mean'] == frame.v0.mean()
            chart = request(c,'POST',f'/api/datasets/{ident}/analysis','group-chart',json={'kind':'chart','spec':{'type':'bar','x':'team','y':'v0','agg':'sum'},'revision':0}).json()
            assert sum(v['value'] for v in chart['series'][0]['data']) == frame.v0.sum()
            operation = {'operation':'sample','params':{'mode':'count','n':1000,'seed':42,'replace':False},'revision':0}
            preview = request(c,'POST',f'/api/datasets/{ident}/preview','sample-preview',json=operation).json()
            assert preview['overview']['rows']==1000
            applied = request(c,'POST',f'/api/datasets/{ident}/operations','sample-apply',json=operation).json()
            undone = request(c,'POST',f'/api/datasets/{ident}/history/undo','undo-100k',json={'revision':applied['revision']}).json()
            assert undone['overview']['rows']==n
            exported = request(c,'GET',f'/api/datasets/{ident}/export/csv','export-100k')
            assert len(pd.read_csv(io.BytesIO(exported.content)))==n
            sessions = []
            for _ in range(args.users):
                other = client()
                od = upload(other,raw,'parallel-user-setup')
                sessions.append((other,od['id']))
            def work(pair):
                user, dataset = pair
                for index in range(args.rounds):
                    value = request(user,'GET',f'/api/datasets/{dataset}/table?offset={index*25}&limit=25','concurrent-table').json()
                    assert value['total']==n and value['ids']==list(range(index*25,index*25+25))
                    stats = request(user,'POST',f'/api/datasets/{dataset}/analysis','concurrent-describe',json={'kind':'describe','revision':0}).json()['rows']
                    assert next(r for r in stats if r['field']=='v0')['mean']==frame.v0.mean()
                    plotted = request(user,'POST',f'/api/datasets/{dataset}/analysis','concurrent-histogram',json={'kind':'chart','spec':{'type':'histogram','x':'v0','bins':15},'revision':0}).json()
                    assert sum(plotted['groups'][0]['hist'])==n
                assert user.get(f'/api/datasets/{ident}').status_code==404
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=args.users) as pool: list(pool.map(work,sessions))
            result['concurrentDurationSeconds'] = round(time.perf_counter()-started,3)
            for user,_ in sessions: user.close()
            race = {'operation':'sample','params':{'mode':'count','n':500,'seed':7,'replace':False},'revision':undone['revision']}
            def commit(_): return c.post(f'/api/datasets/{ident}/operations',json=race)
            with ThreadPoolExecutor(max_workers=2) as pool: raced=list(pool.map(commit,range(2)))
            assert sorted(r.status_code for r in raced)==[200,400]
            assert next(r for r in raced if r.status_code==400).json()['error']=='stale_revision'
            result['concurrentSameRevision'] = 'one commit, one stale_revision, no data corruption'
            request(c,'POST','/api/upload','reject-rows',expected=400,files={'file':('too-many.csv',b'x\n'+b'1\n'*100001)})
            wide201 = pd.DataFrame(np.zeros((2,201)),columns=[f'c{i}' for i in range(201)]).to_csv(index=False).encode()
            request(c,'POST','/api/upload','reject-columns',expected=400,files={'file':('wide.csv',wide201)})
            request(c,'POST','/api/upload','reject-21MB',expected=400,files={'file':('large.csv',b'x\n'+b'1'*(21*1024**2))})
            with client() as limits:
                first=None
                for _ in range(12):
                    created=request(limits,'POST','/api/samples/iris','dataset-limit-setup').json()
                    if first is None: first=created
                assert request(limits,'POST','/api/samples/iris','reject-dataset-13',expected=400).json()['error']=='dataset_limit'
                for _ in range(30):
                    first=request(limits,'POST',f'/api/datasets/{first["id"]}/operations','history-limit-setup',json={'operation':'sample','params':{'mode':'count','n':100,'seed':42,'replace':False},'revision':first['revision']}).json()
                assert request(limits,'POST',f'/api/datasets/{first["id"]}/operations','reject-history-31',expected=400,json={'operation':'sample','params':{'mode':'count','n':100,'seed':42,'replace':False},'revision':first['revision']}).json()['error']=='history_limit'
            if args.wide:
                # Maximum legal shape stays below 20 MiB by using empty fields.
                wide = (','.join(f'c{i}' for i in range(200))+'\n'+''.join(str(i)+','*199+'\n' for i in range(n))).encode()
                assert len(wide)<20*1024**2
                w=upload(c,wide,'upload-max-shape')
                assert w['overview']['rows']==n and w['overview']['columns']==200
                assert request(c,'GET',f'/api/datasets/{w["id"]}/table?limit=25','page-max-shape').json()['total']==n
                wide_op={'operation':'sample','params':{'mode':'count','n':1000,'seed':42,'replace':False},'revision':w['revision']}
                wp=request(c,'POST',f'/api/datasets/{w["id"]}/preview','preview-max-shape',json=wide_op).json()
                assert wp['overview']['rows']==1000 and wp['overview']['columns']==200
                wa=request(c,'POST',f'/api/datasets/{w["id"]}/operations','apply-max-shape',json=wide_op).json()
                wu=request(c,'POST',f'/api/datasets/{w["id"]}/history/undo','undo-max-shape',json={'revision':wa['revision']}).json()
                assert wu['overview']['rows']==n and wu['overview']['missing']==n*199
                result['maximumShape']={'rows':n,'columns':200,'csvBytes':len(wide),'missing':w['overview']['missing']}
            assert not failures,failures
            request(c,'GET','/api/health','final-health')
            result['passed']=True
    except Exception as exc:
        result['passed']=False
        failures.append(repr(exc))
    finally:
        stop.set()
        if process.poll() is None: process.terminate()
        process.wait(timeout=15)
        log.close()
        result['peakRSSMiB']=round(max(memory,default=0)/1024**2,2)
        result['failures']=failures
        result['requests']=samples
        result['metrics']={label:{'requests':len(values),'p50':round(float(np.percentile(values,50)),3),'p95':round(float(np.percentile(values,95)),3),'max':round(max(values),3)} for label in {s['label'] for s in samples} if (values:=[s['seconds'] for s in samples if s['label']==label])}
        (run/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'latest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        disposable=(run/'runtime').resolve()
        assert disposable.parent==run.resolve() and disposable.is_relative_to(out.resolve())
        if disposable.exists():shutil.rmtree(disposable)
        print(json.dumps({k:v for k,v in result.items() if k not in {'requests'}},ensure_ascii=True),flush=True)
        print('Result:',run/'results.json',flush=True)
    return 0 if result['passed'] else 1

if __name__=='__main__': sys.exit(main())
